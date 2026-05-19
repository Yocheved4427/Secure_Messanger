"""
main.py — Application entry point.

HOW TO RUN:
  uvicorn server.main:app --reload

  Then open: http://localhost:8000/docs
  Or connect with: python client.py
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .models import create_tables
from .routes import router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title="Secure Messenger",
    description=(
        "Authenticated, encrypted messaging with real-time Server-Sent Events. "
        "POST /messages saves a message; GET /stream pushes it instantly to connected clients."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(router)
