"""
test_app.py — Full pytest test suite (all Stage 1 routes + GET /stream SSE).

HOW TO RUN:
  pytest tests/ -v

KEY DESIGN DECISIONS:
  - In-memory SQLite with StaticPool so every test session starts clean
    (no stale messenger.db file from previous runs).
  - app.dependency_overrides replaces the real DB with the test DB.
  - SSE tests are async (pytest-asyncio) so they share the SAME event loop
    as the app's ConnectionManager queues — this is essential because
    asyncio.Queue is event-loop-bound. Running in a different loop
    (e.g. via asyncio.run() from a sync test) would silently deadlock.
  - anyio.move_on_after() caps how long we wait for the SSE stream to
    close cleanly, preventing hangs if something goes wrong.
"""

import json
import pytest
import anyio
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.main import app
from server.models import Base, get_db


# ---------------------------------------------------------------------------
# sse-starlette stores AppStatus.should_exit_event as a module-level
# asyncio.Event singleton.  It gets created the first time an SSE connection
# is opened — in the TestClient's event loop.  When pytest-asyncio runs an
# async test it creates a NEW function-scoped event loop.  Reusing the old
# Event in the new loop raises "is bound to a different event loop".
#
# Fix: reset the singleton to None before every test so sse-starlette
# recreates it in whatever event loop is currently active.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_sse_app_status():
    from sse_starlette.sse import AppStatus
    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


# ---------------------------------------------------------------------------
# Isolated in-memory database for the whole test session.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """
    Create a fresh in-memory SQLite DB, override FastAPI's get_db dependency
    to point to it, and yield a TestClient.  Teardown drops all tables.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,   # share ONE connection so all sessions see the same tables
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def alice_token(client):
    r = client.post("/register", json={"username": "alice", "password": "alicepw"})
    assert r.status_code == 201, f"register alice failed: {r.json()}"
    r = client.post("/login", json={"username": "alice", "password": "alicepw"})
    assert r.status_code == 200, f"login alice failed: {r.json()}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def bob_token(client):
    r = client.post("/register", json={"username": "bob", "password": "bobpass"})
    assert r.status_code == 201, f"register bob failed: {r.json()}"
    r = client.post("/login", json={"username": "bob", "password": "bobpass"})
    assert r.status_code == 200, f"login bob failed: {r.json()}"
    return r.json()["access_token"]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — REST routes
# ─────────────────────────────────────────────────────────────────────────────

class TestRegister:
    def test_success(self, client):
        r = client.post("/register", json={"username": "charlie", "password": "charlpw"})
        assert r.status_code == 201

    def test_duplicate(self, client):
        client.post("/register", json={"username": "dupe", "password": "password1"})
        r = client.post("/register", json={"username": "dupe", "password": "password2"})
        assert r.status_code == 400

    def test_short_password(self, client):
        r = client.post("/register", json={"username": "newuser", "password": "abc"})
        assert r.status_code == 422   # Pydantic min_length validation


class TestLogin:
    def test_success(self, client):
        client.post("/register", json={"username": "logintest", "password": "correct"})
        r = client.post("/login", json={"username": "logintest", "password": "correct"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_wrong_password(self, client):
        r = client.post("/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401

    def test_unknown_user(self, client):
        r = client.post("/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401


class TestSendMessage:
    def test_success(self, client, alice_token):
        r = client.post(
            "/messages",
            json={"recipient": "bob", "content": "hello bob"},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["content"] == "hello bob"   # plain text in response
        assert body["sender"] == "alice"
        assert body["recipient"] == "bob"

    def test_unauthenticated(self, client):
        r = client.post("/messages", json={"recipient": "bob", "content": "hi"})
        assert r.status_code == 403    # no token at all

    def test_invalid_token(self, client):
        r = client.post(
            "/messages",
            json={"recipient": "bob", "content": "hi"},
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert r.status_code == 401


class TestGetMessages:
    def test_only_own_messages(self, client, alice_token, bob_token):
        client.post(
            "/messages",
            json={"recipient": "bob", "content": "from alice"},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        client.post(
            "/messages",
            json={"recipient": "alice", "content": "from bob"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )

        r = client.get("/messages", headers={"Authorization": f"Bearer {alice_token}"})
        assert r.status_code == 200
        messages = r.json()
        for m in messages:
            assert m["sender"] == "alice" or m["recipient"] == "alice"

    def test_content_is_decrypted(self, client, alice_token):
        client.post(
            "/messages",
            json={"recipient": "bob", "content": "decrypt me"},
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        r = client.get("/messages", headers={"Authorization": f"Bearer {alice_token}"})
        contents = [m["content"] for m in r.json()]
        assert "decrypt me" in contents


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — SSE stream
# ─────────────────────────────────────────────────────────────────────────────

# ---------------------------------------------------------------------------
# WHY A LIVE SERVER FIXTURE?
#
# httpx.ASGITransport (v0.27) buffers the ENTIRE response body before
# returning to the caller: `await self.app(scope, receive, send)` blocks
# until the ASGI generator finishes.  For an infinite SSE stream that never
# happens, so `http.stream(...)` hangs forever.
#
# The only reliable workaround is to spin up a REAL uvicorn server in a
# background daemon thread.  Because it's in-process it shares:
#   • app.dependency_overrides  → same in-memory SQLite DB as TestClient
#   • ConnectionManager.manager → same singleton, same Queue objects
# So the SSE tests can make genuine HTTP connections and watch events flow.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def live_server_url(client):   # `client` must run first so DB override is set
    """
    Start a real uvicorn server in a daemon thread.
    Returns the base URL, e.g. 'http://127.0.0.1:18123'.
    """
    import asyncio as _asyncio
    import socket
    import threading
    import time

    import uvicorn

    # Pick a free OS port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    base_url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run_server():
        # Run in a new event loop so it doesn't interfere with pytest's loop.
        _asyncio.run(server.serve())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait until the server is ready (max 5 s).
    for _ in range(100):
        try:
            httpx.get(f"{base_url}/docs", timeout=0.2)
            break
        except Exception:
            time.sleep(0.05)

    yield base_url

    server.should_exit = True   # signal graceful shutdown


class TestSSEStream:
    def test_stream_requires_auth(self, client):
        """GET /stream without a token should be rejected."""
        r = client.get("/stream")
        assert r.status_code == 403

    def test_stream_invalid_token(self, client):
        r = client.get(
            "/stream",
            headers={"Authorization": "Bearer bad.token.here"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_stream_opens_successfully(self, live_server_url, alice_token):
        """
        With a valid token the server should respond 200 with
        Content-Type: text/event-stream.

        We connect to a real uvicorn server so httpx can truly stream the
        response without buffering the infinite SSE body.  The generator
        yields a ": connected" comment immediately on open, so we don't
        need to wait for a keep-alive timeout.
        """
        async with httpx.AsyncClient(base_url=live_server_url) as http:
            with anyio.move_on_after(5):
                async with http.stream(
                    "GET",
                    "/stream",
                    headers={"Authorization": f"Bearer {alice_token}"},
                ) as r:
                    assert r.status_code == 200
                    assert "text/event-stream" in r.headers.get("content-type", "")
                    # Read the first line (": connected") then exit.
                    async for _ in r.aiter_lines():
                        break

    @pytest.mark.asyncio
    async def test_message_is_pushed_to_stream(self, live_server_url, alice_token, bob_token):
        """
        After Bob opens a stream, Alice sends him a message.
        The event should arrive through the SSE connection within seconds.

        HOW THE CONCURRENCY WORKS:
          anyio.create_task_group() runs both coroutines concurrently:
            • read_stream(): opens Bob's SSE feed, waits for a data line
            • send_msg():    waits 0.3 s (so the stream is registered),
                             then POSTs a message from Alice to Bob
          When the "data:" line arrives read_stream() saves it and returns.
          anyio.move_on_after(10) prevents the test from hanging if something
          goes wrong.
        """
        received: list[dict] = []

        async with httpx.AsyncClient(base_url=live_server_url) as http:

            async def read_stream() -> None:
                with anyio.move_on_after(10):
                    async with http.stream(
                        "GET",
                        "/stream",
                        headers={"Authorization": f"Bearer {bob_token}"},
                    ) as r:
                        async for line in r.aiter_lines():
                            if line.startswith("data:"):
                                payload = line[len("data:"):].strip()
                                if payload:
                                    received.append(json.loads(payload))
                                    return   # got the message, exit cleanly

            async def send_msg() -> None:
                await anyio.sleep(0.3)   # give read_stream() time to register
                await http.post(
                    "/messages",
                    json={"recipient": "bob", "content": "live delivery test"},
                    headers={"Authorization": f"Bearer {alice_token}"},
                )

            async with anyio.create_task_group() as tg:
                tg.start_soon(read_stream)
                tg.start_soon(send_msg)

        assert received, "No SSE event received within timeout"
        assert received[0].get("content") == "live delivery test"
        assert received[0].get("sender") == "alice"
        assert received[0].get("recipient") == "bob"
