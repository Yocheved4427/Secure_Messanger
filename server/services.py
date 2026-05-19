"""
services.py — Business logic layer.

RESPONSIBILITY:
  Orchestrate encryption/decryption, password hashing, token creation,
  SSE broadcasts, and building Pydantic response objects.
  Services call the repository for DB access; routes call services.

  Routes:    HTTP in / HTTP out
  Services:  business rules + orchestration
  Repository: SQL in / ORM objects out
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import hash_password, verify_password, create_token
from .crypto import encrypt, decrypt
from .schemas import MessageResponse, TokenResponse
from .sse import manager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth services
# ---------------------------------------------------------------------------

def register_user(db: Session, username: str, password: str) -> dict:
    if repo.get_user_by_username(db, username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username already taken",
        )
    repo.create_user(db, username, hash_password(password))
    log.info("Registered user: %s", username)
    return {"message": "User registered successfully"}


def login_user(db: Session, username: str, password: str) -> TokenResponse:
    user = repo.get_user_by_username(db, username)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    new_version = repo.increment_login_version(db, user)
    token = create_token(username, new_version)
    log.info("Login: %s (version=%d)", username, new_version)
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Message services
# ---------------------------------------------------------------------------

async def send_messages(
    db: Session,
    sender: str,
    recipients: list[str],
    content: str,
) -> list[MessageResponse]:
    """
    Encrypt content once, persist one Message row per recipient,
    then push SSE events to each recipient and the sender.
    """
    ciphertext = encrypt(content)
    responses: list[MessageResponse] = []

    for recipient in recipients:
        msg = repo.create_message(db, sender, recipient, ciphertext)
        log.info("Message from %s to %s (id=%d)", sender, recipient, msg.id)
        response = MessageResponse(
            id=msg.id,
            sender=msg.sender,
            recipient=msg.recipient,
            content=content,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        )
        responses.append(response)

        event_data = response.model_dump_json()
        await manager.push(recipient, event_data)
        if recipient != sender:
            await manager.push(sender, event_data)

    return responses


def fetch_messages(db: Session, username: str) -> list[MessageResponse]:
    messages = repo.get_messages_for_user(db, username)
    return [
        MessageResponse(
            id=msg.id,
            sender=msg.sender,
            recipient=msg.recipient,
            content=decrypt(msg.ciphertext),
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        )
        for msg in messages
    ]


def edit_message(db: Session, message_id: int, new_content: str, requesting_user: str) -> MessageResponse:
    msg = repo.get_message_by_id(db, message_id)
    if not msg or msg.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.sender != requesting_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the sender can edit this message")

    updated = repo.update_message_content(db, msg, encrypt(new_content))
    return MessageResponse(
        id=updated.id,
        sender=updated.sender,
        recipient=updated.recipient,
        content=new_content,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


def delete_message(db: Session, message_id: int, requesting_user: str) -> dict:
    msg = repo.get_message_by_id(db, message_id)
    if not msg or msg.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.sender != requesting_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the sender can delete this message")

    repo.soft_delete_message(db, msg)
    log.info("Message %d soft-deleted by %s", message_id, requesting_user)
    return {"message": "Message deleted"}
