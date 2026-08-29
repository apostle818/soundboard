import importlib
import sys

import dotenv
import pytest


def _import_app_fresh(monkeypatch, tmp_path):
    # A developer's local .env must not decide the outcome of this test.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("SOUNDBOARD_SOUNDS_DIR", str(tmp_path / "sounds"))
    monkeypatch.setenv("SOUNDBOARD_DB_FILE", str(tmp_path / "sounds_db.json"))
    monkeypatch.setenv("SOUNDBOARD_USERS_DB", str(tmp_path / "users.db"))
    sys.modules.pop("app", None)
    try:
        return importlib.import_module("app")
    finally:
        sys.modules.pop("app", None)


def test_startup_fails_without_secret_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _import_app_fresh(monkeypatch, tmp_path)


def test_startup_fails_on_empty_secret_key(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _import_app_fresh(monkeypatch, tmp_path)


def test_startup_uses_secret_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "from-the-environment")
    assert _import_app_fresh(monkeypatch, tmp_path).SECRET_KEY == "from-the-environment"
