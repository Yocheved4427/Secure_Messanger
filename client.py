"""
client.py — Interactive CLI client for Secure Messenger.

HOW TO RUN:
  python client.py

  Open multiple terminals with different users to see messages appear live.

WHAT IT DOES:
  1. Asks for your username and password, logs in, gets a JWT.
  2. Starts a background thread that keeps GET /stream open.
     Whenever the server pushes an event, the thread prints it immediately.
  3. The main thread reads your input in a loop so you can send messages
     while simultaneously receiving them.

INPUT FORMAT:
  recipient: message text

  Examples:
    bob: hey, are you there?
    alice: yes! what's up?

  Type  quit  or press Ctrl-C to exit.

WHY TWO THREADS?
  Listening to an SSE stream is a blocking operation — it sits and waits
  for bytes indefinitely.  If we did that in the main thread, we could
  never type anything.

  Python threads let us do both at once:
    Thread 1 (background): blocks on the HTTP stream, prints messages.
    Thread 2 (main):       reads keyboard input, sends messages.
"""

import json
import sys
import threading

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"


# ─────────────────────────────────────────────────────────────────────────────
# Authentication helpers
# ─────────────────────────────────────────────────────────────────────────────

def register(base_url: str, username: str, password: str) -> None:
    """Try to register the user. Ignore 400 (username taken) silently."""
    r = httpx.post(f"{base_url}/register", json={"username": username, "password": password})
    if r.status_code == 201:
        print(f"  [+] Registered new account for '{username}'.")
    elif r.status_code == 400:
        pass  # account already exists — just log in
    else:
        r.raise_for_status()


def login(base_url: str, username: str, password: str) -> str:
    """Log in and return the JWT access token."""
    r = httpx.post(f"{base_url}/login", json={"username": username, "password": password})
    if r.status_code == 401:
        print("  [!] Wrong password.")
        sys.exit(1)
    r.raise_for_status()
    return r.json()["access_token"]


# ─────────────────────────────────────────────────────────────────────────────
# SSE listener (runs in a background thread)
# ─────────────────────────────────────────────────────────────────────────────

def _sse_listener(base_url: str, token: str, my_username: str, stop_event: threading.Event) -> None:
    """
    Opens GET /stream and prints incoming messages until the connection
    closes or stop_event is set.

    SSE wire format:
        data: {"sender": "alice", "content": "hi", ...}\n\n

    Lines starting with ": " are keep-alive comments — we skip them.
    """
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.stream("GET", f"{base_url}/stream", headers=headers, timeout=None) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if stop_event.is_set():
                    break

                if not line.startswith("data:"):
                    continue  # skip blank lines and keep-alive/connected comments

                raw = line[len("data:"):].strip()
                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                sender    = msg.get("sender", "?")
                recipient = msg.get("recipient", "?")
                content   = msg.get("content", "")

                if sender == my_username:
                    print(f"\r  → you → {recipient}: {content}")
                else:
                    print(f"\r  ← {sender}: {content}")

                print("send> ", end="", flush=True)

    except httpx.HTTPStatusError as exc:
        print(f"\n  [!] Stream error: {exc.response.status_code} {exc.response.text}")
    except Exception as exc:
        if not stop_event.is_set():
            print(f"\n  [!] Stream disconnected: {exc}")
    finally:
        stop_event.set()


# ─────────────────────────────────────────────────────────────────────────────
# Message sender (main thread)
# ─────────────────────────────────────────────────────────────────────────────

def _send_message(base_url: str, token: str, recipient: str, content: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    r = httpx.post(
        f"{base_url}/messages",
        json={"recipient": recipient, "content": content},
        headers=headers,
    )
    if r.status_code not in (200, 201):
        print(f"  [!] Failed to send: {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("╔══════════════════════════════════════╗")
    print("║       Secure Messenger  CLI          ║")
    print("╚══════════════════════════════════════╝")
    print()

    base_url = input(f"Server URL [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    username = input("Username: ").strip()
    password = input("Password: ").strip()

    print()
    print("  Connecting …")

    register(base_url, username, password)
    token = login(base_url, username, password)
    print(f"  [+] Logged in as '{username}'.")
    print()
    print("  Listening for incoming messages (GET /stream is now open).")
    print()
    print("  To send:  recipient: your message here")
    print("  To quit:  type 'quit' or press Ctrl-C")
    print()

    stop_event = threading.Event()

    listener = threading.Thread(
        target=_sse_listener,
        args=(base_url, token, username, stop_event),
        daemon=True,
    )
    listener.start()

    try:
        while not stop_event.is_set():
            try:
                line = input("send> ").strip()
            except EOFError:
                break

            if not line:
                continue

            if line.lower() == "quit":
                break

            if ":" not in line:
                print("  [?] Format: recipient: message text")
                continue

            recipient, _, content = line.partition(":")
            recipient = recipient.strip()
            content   = content.strip()

            if not recipient or not content:
                print("  [?] Both recipient and message are required.")
                continue

            _send_message(base_url, token, recipient, content)

    except KeyboardInterrupt:
        pass

    print("\n  Goodbye.")
    stop_event.set()


if __name__ == "__main__":
    main()
