"""
schemas.py — The shapes of requests and responses (Pydantic models).

WHAT IS A SCHEMA?
  A schema describes what JSON the API expects to receive, and what it returns.
  FastAPI uses these classes to:
    - Validate incoming requests (missing/wrong field → instant 422 error)
    - Generate the /docs page automatically
    - Keep DB models (storage) separate from API shapes (transport)
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    content:   str = Field(min_length=1, max_length=2000)
    recipient: str = Field(min_length=3, max_length=50)


class MessageResponse(BaseModel):
    id:         int
    sender:     str
    recipient:  str
    content:    str       # always decrypted plain text — never expose ciphertext
    created_at: datetime

    model_config = {"from_attributes": True}
