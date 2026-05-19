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


def create_token(username: str) -> str:
    """Build a signed JWT with the username and expiry time."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Decode the token and return the username. Return None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    """
    FastAPI dependency: extract the Bearer token, validate it, return username.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return username
