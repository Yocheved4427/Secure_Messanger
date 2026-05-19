"""
repository.py — All direct database access (SQLAlchemy queries).

THE REPOSITORY PATTERN:
  Route handlers and services never call db.query() directly.
  Every SQL operation lives here as a plain function that receives
  a `db: Session` and returns ORM objects (or None).

  Benefits:
    - One place to change if the DB schema or ORM version changes.
    - Easy to mock in unit tests without touching routes or services.
    - Clear separation: routes handle HTTP, services handle logic, repo handles data.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .models import User, Message


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash, login_version=1)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def increment_login_version(db: Session, user: User) -> int:
    """Bump login_version and return the new value. Called on every successful login."""
    user.login_version += 1
    db.commit()
    db.refresh(user)
    return user.login_version


# ---------------------------------------------------------------------------
# Message queries
# ---------------------------------------------------------------------------

def create_message(db: Session, sender: str, recipient: str, ciphertext: str) -> Message:
    msg = Message(sender=sender, recipient=recipient, ciphertext=ciphertext)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages_for_user(db: Session, username: str) -> list[Message]:
    """Return all non-deleted messages where the user is sender or recipient."""
    return (
        db.query(Message)
        .filter(
            (Message.sender == username) | (Message.recipient == username),
            Message.is_deleted == False,  # noqa: E712
        )
        .order_by(Message.created_at)
        .all()
    )


def get_message_by_id(db: Session, message_id: int) -> Optional[Message]:
    return db.query(Message).filter(Message.id == message_id).first()


def update_message_content(db: Session, msg: Message, ciphertext: str) -> Message:
    msg.ciphertext  = ciphertext
    msg.updated_at  = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)
    return msg


def soft_delete_message(db: Session, msg: Message) -> Message:
    msg.is_deleted = True
    db.commit()
    db.refresh(msg)
    return msg
