"""Regression test for the /api/auth username-enumeration timing gap.

Before the fix, an unknown username returned immediately after one SQLite
lookup, while a known username with the wrong password additionally paid the
cost of werkzeug's password hash check (scrypt by default, tens of
milliseconds) — a difference large enough to time-enumerate valid usernames
remotely. The fix checks a dummy hash on the "no such user" path so both
paths call check_password_hash exactly once.

This asserts the call happens (functional), not how long it takes (timing
assertions are flaky under CI load) — see docs on this fix in CLAUDE.md.
"""


def test_unknown_username_still_checks_a_password_hash(soundboard, monkeypatch):
    calls = []
    real_check = soundboard.check_password_hash

    def spy(pwhash, password):
        calls.append(pwhash)
        return real_check(pwhash, password)

    monkeypatch.setattr(soundboard, "check_password_hash", spy)

    with soundboard.app.test_client() as client:
        resp = client.post("/api/auth", json={"username": "mallory", "password": "whatever"})

    assert resp.status_code == 401
    assert len(calls) == 1
    assert calls[0] == soundboard._DUMMY_PASSWORD_HASH


def test_known_username_wrong_password_checks_its_own_hash(soundboard, monkeypatch):
    calls = []
    real_check = soundboard.check_password_hash

    def spy(pwhash, password):
        calls.append(pwhash)
        return real_check(pwhash, password)

    monkeypatch.setattr(soundboard, "check_password_hash", spy)

    with soundboard.app.test_client() as client:
        resp = client.post("/api/auth", json={"username": "alice", "password": "wrong"})

    assert resp.status_code == 401
    assert len(calls) == 1
    assert calls[0] != soundboard._DUMMY_PASSWORD_HASH
