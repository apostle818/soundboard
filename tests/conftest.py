import importlib
import sys

import pytest
from werkzeug.security import generate_password_hash

# Minimal but structurally valid samples for each container we accept.
WAV_BYTES  = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x10\x00\x00\x00" \
             + b"\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00" \
             + b"data" + (0).to_bytes(4, "little")
MP3_BYTES  = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 64
OGG_BYTES  = b"OggS\x00\x02" + b"\x00" * 64
WEBM_BYTES = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1f\x42\x86\x81\x01" \
             b"\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08\x42\x82\x84webm" \
             + b"\x00" * 32
M4A_BYTES  = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom" + b"\x00" * 32


@pytest.fixture
def soundboard(tmp_path, monkeypatch):
    """Import app.py fresh against throwaway storage paths."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SOUNDBOARD_SOUNDS_DIR", str(tmp_path / "sounds"))
    monkeypatch.setenv("SOUNDBOARD_DB_FILE", str(tmp_path / "sounds_db.json"))
    monkeypatch.setenv("SOUNDBOARD_USERS_DB", str(tmp_path / "users.db"))
    sys.modules.pop("app", None)
    module = importlib.import_module("app")

    conn = module.users_conn()
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("alice", generate_password_hash("hunter2")),
    )
    conn.commit()
    conn.close()

    module.app.config["TESTING"] = True
    yield module
    sys.modules.pop("app", None)


@pytest.fixture
def client(soundboard):
    with soundboard.app.test_client() as c:
        yield c


@pytest.fixture
def token(client):
    resp = client.post("/api/auth", json={"username": "alice", "password": "hunter2"})
    assert resp.status_code == 200
    return resp.get_json()["token"]
