"""
routes.py — FastAPI route handlers.

RESPONSIBILITIES (only these):
  - Declare HTTP endpoints (method + path).
  - Extract FastAPI dependencies (get_db, require_auth, path/body params).
  - Delegate ALL business logic to services.py.
  - Return the value produced by the service.

Routes never touch db.query(), encrypt/decrypt, or hash directly.

ENDPOINTS:
  POST /register                  — create an account
  POST /login                     — exchange credentials for a JWT token
  POST /messages                  — send encrypted messages to recipients   [JWT required]
  GET  /messages                  — fetch your message history              [JWT required]
  PUT  /messages/{id}             — edit a sent message                     [JWT required]
  DELETE /messages/{id}           — soft-delete a sent message              [JWT required]
  GET  /stream                    — live SSE feed                           [JWT required]
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .models import get_db
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, EditMessageRequest, MessageResponse,
)
from .auth import require_auth
from .sse import manager
from . import services

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    return services.register_user(db, body.username, body.password)


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    return services.login_user(db, body.username, body.password)


# ---------------------------------------------------------------------------
# POST /messages
# ---------------------------------------------------------------------------
@router.post("/messages", response_model=list[MessageResponse], status_code=status.HTTP_201_CREATED)
async def send_message(
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    return await services.send_messages(db, username, body.recipients, body.content)


# ---------------------------------------------------------------------------
# GET /messages
# ---------------------------------------------------------------------------
@router.get("/messages", response_model=list[MessageResponse])
def get_messages(
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    return services.fetch_messages(db, username)


# ---------------------------------------------------------------------------
# PUT /messages/{id}
# ---------------------------------------------------------------------------
@router.put("/messages/{message_id}", response_model=MessageResponse)
def edit_message(
    message_id: int,
    body: EditMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    return services.edit_message(db, message_id, body.content, username)


# ---------------------------------------------------------------------------
# DELETE /messages/{id}
# ---------------------------------------------------------------------------
@router.delete("/messages/{message_id}", status_code=status.HTTP_200_OK)
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    return services.delete_message(db, message_id, username)


# ---------------------------------------------------------------------------
# GET /stream  — SSE endpoint
# ---------------------------------------------------------------------------
@router.get("/stream")
async def stream(
    request: Request,
    username: str = Depends(require_auth),
):
    queue = manager.connect(username)
    log.info("SSE stream opened for %s", username)

    async def event_generator():
        try:
            yield {"comment": "connected"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {"data": data}
                except asyncio.TimeoutError:
                    yield {"comment": "keep-alive"}
        finally:
            manager.disconnect(username, queue)
            log.info("SSE stream closed for %s", username)

    return EventSourceResponse(event_generator())

