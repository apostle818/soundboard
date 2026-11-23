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


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " true "])
def test_debug_enabled_when_env_var_set(soundboard, monkeypatch, value):
    monkeypatch.setenv("SOUNDBOARD_DEBUG", value)
    assert soundboard.debug_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
def test_debug_disabled_by_default(soundboard, monkeypatch, value):
    monkeypatch.setenv("SOUNDBOARD_DEBUG", value)
    assert soundboard.debug_enabled() is False


def test_debug_disabled_when_env_var_absent(soundboard, monkeypatch):
    monkeypatch.delenv("SOUNDBOARD_DEBUG", raising=False)
    assert soundboard.debug_enabled() is False


def test_startup_fails_on_the_env_example_placeholder(monkeypatch, tmp_path):
    # The value .env.example ships is public; `cp .env.example .env` must not
    # produce a running app whose tokens anyone can forge.
    monkeypatch.setenv("SECRET_KEY", "change-this-to-a-long-random-string")
    with pytest.raises(RuntimeError, match="placeholder"):
        _import_app_fresh(monkeypatch, tmp_path)


def test_the_rejected_placeholder_is_the_one_env_example_ships():
    from pathlib import Path
    example = Path(__file__).resolve().parent.parent / ".env.example"
    line = next(l for l in example.read_text().splitlines() if l.startswith("SECRET_KEY="))
    assert line.split("=", 1)[1] == "change-this-to-a-long-random-string"
