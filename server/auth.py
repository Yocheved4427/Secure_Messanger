"""
auth.py — Password hashing and JWT token logic.

CONCEPT 1 — WHY WE HASH PASSWORDS
  bcrypt is a ONE-WAY function:
    hash("secret123") → "$2b$12$eImiTXuW..." (a fingerprint)
  At login we re-hash the typed password and compare — never reverse.

CONCEPT 2 — WHY WE USE JWT TOKENS
  After login the server gives the client a signed JWT (JSON Web Token).
  Think of it as a wristband: proves identity without re-checking the DB.
  Payload has the username and an expiry time. Signature prevents tampering.

CONCEPT 3 — FASTAPI DEPENDENCY INJECTION
  require_auth() is declared once here and injected into any route that needs it:
      def my_route(username: str = Depends(require_auth)):
  FastAPI calls it automatically before the route runs.
  Missing/invalid token → HTTP 401, the route never executes.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .models import User, get_db


SECRET_KEY = "change-this-to-a-long-random-string-in-production"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

_bearer = HTTPBearer()


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the password. Store this, never the plain text."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if the plain password matches the stored hash. Used at login."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(username: str, login_version: int) -> str:
    """Build a signed JWT with the username, login_version, and expiry time."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "ver": login_version, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[tuple[str, int]]:
    """
    Decode the token and return (username, login_version).
    Returns None if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        version  = payload.get("ver", 1)
        if username is None:
            return None
        return username, version
    except JWTError:
        return None


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> str:
    """
    FastAPI dependency: validate the Bearer token AND verify that
    the login_version in the JWT still matches the one in the DB.
    Raises HTTP 401 on any mismatch (invalid token, expired, or session revoked).
    Returns the username on success.
    """
    decoded = decode_token(credentials.credentials)
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")
    username, token_version = decoded

    user = db.query(User).filter(User.username == username).first()
    if user is None or user.login_version != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session invalidated — please log in again")
    return username
