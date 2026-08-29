import io

from conftest import WAV_BYTES


def test_max_content_length_is_configured(soundboard):
    assert soundboard.app.config["MAX_CONTENT_LENGTH"] == soundboard.MAX_UPLOAD_MB * 1024 * 1024
    assert soundboard.MAX_UPLOAD_MB == 25


def test_max_upload_mb_is_configurable(monkeypatch, tmp_path):
    import importlib
    import sys

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SOUNDBOARD_MAX_UPLOAD_MB", "3")
    monkeypatch.setenv("SOUNDBOARD_SOUNDS_DIR", str(tmp_path / "sounds"))
    monkeypatch.setenv("SOUNDBOARD_DB_FILE", str(tmp_path / "sounds_db.json"))
    monkeypatch.setenv("SOUNDBOARD_USERS_DB", str(tmp_path / "users.db"))
    sys.modules.pop("app", None)
    try:
        module = importlib.import_module("app")
        assert module.app.config["MAX_CONTENT_LENGTH"] == 3 * 1024 * 1024
    finally:
        sys.modules.pop("app", None)


def test_oversized_upload_is_rejected(client, token, soundboard):
    soundboard.app.config["MAX_CONTENT_LENGTH"] = 1024
    resp = client.post(
        "/api/sounds",
        data={
            "token": token,
            "name": "Huge",
            "file": (io.BytesIO(WAV_BYTES + b"\x00" * 4096), "huge.wav"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413
    assert "error" in resp.get_json()


def test_oversized_upload_is_not_written_to_disk(client, token, soundboard):
    soundboard.app.config["MAX_CONTENT_LENGTH"] = 1024
    client.post(
        "/api/sounds",
        data={
            "token": token,
            "name": "Huge",
            "file": (io.BytesIO(WAV_BYTES + b"\x00" * 4096), "huge.wav"),
        },
        content_type="multipart/form-data",
    )
    assert list(soundboard.SOUNDS_DIR.iterdir()) == []
    assert client.get("/api/sounds").get_json() == []
