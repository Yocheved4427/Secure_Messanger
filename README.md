# Secure Messenger

A small messaging service built with FastAPI. Users register, log in, send messages to one or more recipients, and receive new messages and presence updates live over Server-Sent Events. Message contents are encrypted at rest.

[Demo video](Demo.mp4)

## Features

- **Accounts:** registration and login, passwords hashed with bcrypt, JWT bearer tokens
- **Messaging:** send to several recipients at once, fetch your own history, edit a message you sent, soft-delete a message you sent
- **Live updates:** a `GET /stream` SSE connection pushes new messages and `online` / `offline` presence events to connected users
- **Encryption at rest:** message text is stored encrypted with AES-256-GCM (a fresh nonce per message, so identical messages look different, and tampering is detected)
- **Database migrations:** SQLAlchemy models with Alembic migrations
- **CLI client:** a terminal client that listens to the stream on a background thread while you type
- **Tests:** 15 pytest tests covering registration, login, authorization, message visibility, decryption and the SSE stream

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/register` | no | Create an account |
| POST | `/login` | no | Exchange credentials for a JWT |
| POST | `/messages` | JWT | Send a message to one or more recipients |
| GET | `/messages` | JWT | Your message history |
| PUT | `/messages/{id}` | JWT | Edit a message you sent |
| DELETE | `/messages/{id}` | JWT | Soft-delete a message you sent |
| GET | `/stream` | JWT | Live SSE feed (messages and presence) |

Interactive docs are at `http://localhost:8000/docs` once the server is running.

## Structure

```
server/
  routes.py      HTTP endpoints only; delegates to services
  services.py    business logic
  repository.py  database access
  auth.py        password hashing and JWT dependency
  crypto.py      AES-256-GCM encrypt / decrypt
  sse.py         connection manager and presence tracking
  models.py      SQLAlchemy models
  schemas.py     Pydantic request / response models
alembic/         database migrations
client.py        interactive CLI client
seed.py          creates demo users and a first message
tests/           pytest suite
```

## Run it

```bash
pip install -r requirements.txt
uvicorn server.main:app --reload
```

In other terminals:

```bash
python seed.py       # optional: creates alice and bob
python client.py     # log in and chat; open several terminals to see live delivery
pytest               # run the tests
```

## Known limitations

- The encryption key is generated at server start, so messages stored by a previous run cannot be decrypted after a restart. In a real deployment the key would come from an environment variable or a secrets manager.
- Encryption is server-side at rest, not end-to-end: the server can read messages.

## Tech

Python, FastAPI, SQLAlchemy, Alembic, SSE (sse-starlette), JWT (python-jose), bcrypt, cryptography, pytest.
