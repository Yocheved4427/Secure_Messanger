"""
routes.py — All API route handlers, including the SSE stream.

WHAT IS SSE?
  Server-Sent Events (SSE) is just plain HTTP with two rules:
    1. Content-Type: text/event-stream
    2. Each event is "field: value" lines followed by a blank line.

  The simplest event looks like:
        data: {"sender": "alice", "content": "hi"}\n\n

  sse-starlette handles this formatting for us.

HOW THE MESSAGE PIPELINE WORKS:
  Alice  →  POST /messages  →  DB save  →  manager.push("bob", json)
                                                     ↓
                               Bob's open /stream ←  Queue.get()
                                        ↓
                               Bob sees the message instantly

THE FIVE ROUTES:
  POST /register  — create an account
  POST /login     — exchange credentials for a JWT token
  POST /messages  — send an encrypted message     [JWT required]
  GET  /messages  — fetch your message history    [JWT required]
  GET  /stream    — open a live SSE feed           [JWT required]
"""

import json
import logging
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .models import User, Message, get_db
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse,
)
from .auth import hash_password, verify_password, create_token, require_auth
from .crypto import encrypt, decrypt
from .sse import manager


log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username already taken",
        )
    new_user = User(
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(new_user)
    db.commit()
    log.info("Registered user: %s", body.username)
    return {"message": "User registered successfully"}


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_token(user.username)
    log.info("Login: %s", user.username)
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# POST /messages  — send a message, then push it to any live SSE streams
# ---------------------------------------------------------------------------
@router.post("/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    # 1. Persist (encrypted) to the database
    new_msg = Message(
        sender=username,
        recipient=body.recipient,
        ciphertext=encrypt(body.content),
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    log.info("Message from %s to %s", username, body.recipient)

    # 2. Build the response payload (plain-text content, never ciphertext)
    response = MessageResponse(
        id=new_msg.id,
        sender=new_msg.sender,
        recipient=new_msg.recipient,
        content=body.content,
        created_at=new_msg.created_at,
    )

    # 3. Push a real-time SSE event to the recipient AND the sender
    #    so both sides see the message appear instantly in their terminal.
    event_data = response.model_dump_json()
    await manager.push(body.recipient, event_data)
    if body.recipient != username:          # don't double-push to self
        await manager.push(username, event_data)

    return response


# ---------------------------------------------------------------------------
# GET /messages  — fetch message history
# ---------------------------------------------------------------------------
@router.get("/messages", response_model=list[MessageResponse])
def get_messages(
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    messages = (
        db.query(Message)
        .filter((Message.sender == username) | (Message.recipient == username))
        .order_by(Message.created_at)
        .all()
    )
    return [
        MessageResponse(
            id=msg.id,
            sender=msg.sender,
            recipient=msg.recipient,
            content=decrypt(msg.ciphertext),
            created_at=msg.created_at,
        )
        for msg in messages
    ]


# ---------------------------------------------------------------------------
# GET /stream  — SSE endpoint (the core of Stage 2)
# ---------------------------------------------------------------------------
@router.get("/stream")
async def stream(
    request: Request,
    username: str = Depends(require_auth),
):
    """
    Keep this HTTP connection open and push JSON events as they arrive.

    HOW IT WORKS:
      1. A Queue is created for this specific connection and registered
         with the ConnectionManager.
      2. The event generator immediately yields a "connected" comment so
         clients know the stream is ready.
      3. The generator then loops forever, waiting on queue.get().
      4. When POST /messages is called, manager.push() drops a JSON
         string into every matching Queue.
      5. queue.get() unblocks, and sse-starlette sends:
             data: {"sender": "alice", ...}\n\n
      6. If the client disconnects, request.is_disconnected() becomes
         True on the next iteration and we clean up the Queue.

    AUTHENTICATION:
      The JWT is validated by require_auth() before this function runs.
      If the token is missing or invalid the client gets HTTP 401 and
      no connection is established.
    """
    queue = manager.connect(username)
    log.info("SSE stream opened for %s", username)

    async def event_generator():
        try:
            # Yield an immediate comment so the client knows the stream is ready.
            # This also lets tests detect a live connection without waiting for
            # the first keep-alive timeout.
            yield {"comment": "connected"}

            while True:
                # Detect a closed connection without blocking forever
                if await request.is_disconnected():
                    break

                try:
                    # Wait up to 1 second for a new event.
                    # The short timeout lets is_disconnected() be checked
                    # promptly and keeps the connection alive through proxies.
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {"data": data}
                except asyncio.TimeoutError:
                    # No message in the last second — send a keep-alive comment
                    yield {"comment": "keep-alive"}

        finally:
            manager.disconnect(username, queue)
            log.info("SSE stream closed for %s", username)

    return EventSourceResponse(event_generator())
