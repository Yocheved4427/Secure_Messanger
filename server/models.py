"""
models.py — Database tables as Python classes (SQLAlchemy ORM).

WHAT IS AN ORM?
  Instead of writing raw SQL like:
      CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, ...)
  you write a Python class and SQLAlchemy creates the table for you.
  Reading and writing rows becomes reading and writing Python objects.

THE TWO TABLES:

  User — one row per registered user
    id            : integer, primary key
    username      : string, must be unique
    password_hash : string  (NEVER store the plain password — only the hash)
    created_at    : datetime, set automatically when the row is created

  Message — one row per sent message
    id         : integer, primary key
    sender     : string
    recipient  : string
    ciphertext : text    (AES-encrypted content — NEVER store plain text)
    created_at : datetime, set automatically when the row is created
"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


DATABASE_URL = "sqlite:///./messenger.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """
    FastAPI dependency — opens a DB session for one request, closes it after.
    Usage in routes:
        def my_route(db: Session = Depends(get_db)):
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    username:      Mapped[str]      = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str]      = mapped_column(String(255), nullable=False)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Message(Base):
    __tablename__ = "messages"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    sender:     Mapped[str]      = mapped_column(String(50), nullable=False, index=True)
    recipient:  Mapped[str]      = mapped_column(String(50), nullable=False, index=True)
    ciphertext: Mapped[str]      = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


def create_tables():
    """Creates all tables in the database if they don't exist yet."""
    Base.metadata.create_all(bind=engine)
