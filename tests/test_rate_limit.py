def test_auth_allows_attempts_under_the_limit(client):
    for _ in range(9):
        resp = client.post("/api/auth", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401


def test_auth_blocks_after_the_limit_is_reached(client):
    for _ in range(10):
        client.post("/api/auth", json={"username": "alice", "password": "wrong"})

    resp = client.post("/api/auth", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_rate_limit_also_blocks_correct_credentials_once_tripped(client):
    for _ in range(10):
        client.post("/api/auth", json={"username": "alice", "password": "wrong"})

    resp = client.post("/api/auth", json={"username": "alice", "password": "hunter2"})
    assert resp.status_code == 429


def test_rate_limit_is_scoped_per_ip(client):
    for _ in range(10):
        client.post("/api/auth", json={"username": "alice", "password": "wrong"},
                     environ_overrides={"REMOTE_ADDR": "10.0.0.1"})

    blocked = client.post("/api/auth", json={"username": "alice", "password": "wrong"},
                           environ_overrides={"REMOTE_ADDR": "10.0.0.1"})
    assert blocked.status_code == 429

    other_ip = client.post("/api/auth", json={"username": "alice", "password": "hunter2"},
                            environ_overrides={"REMOTE_ADDR": "10.0.0.2"})
    assert other_ip.status_code == 200


def test_rate_limit_window_expires(soundboard, client, monkeypatch):
    for _ in range(10):
        client.post("/api/auth", json={"username": "alice", "password": "wrong"})
    assert client.post("/api/auth", json={"username": "alice", "password": "wrong"}).status_code == 429

    # Fast-forward past the rate-limit window instead of sleeping in the test.
    real_time = soundboard.time.time
    monkeypatch.setattr(soundboard.time, "time",
                         lambda: real_time() + soundboard.AUTH_RATE_WINDOW + 1)

    resp = client.post("/api/auth", json={"username": "alice", "password": "hunter2"})
    assert resp.status_code == 200
