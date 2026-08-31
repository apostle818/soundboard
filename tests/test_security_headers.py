def test_response_sets_hardening_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in resp.headers


def test_csp_restricts_framing_and_objects(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp


def test_csp_allows_the_google_fonts_the_page_actually_loads(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp


def test_headers_present_on_api_responses_too(client):
    resp = client.get("/api/sounds")
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_served_sound_still_sets_nosniff(client, token):
    import io
    from conftest import WAV_BYTES

    upload = client.post(
        "/api/sounds",
        data={"token": token, "name": "Clip", "category": "General",
              "file": (io.BytesIO(WAV_BYTES), "clip.wav")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.get(f"/sounds/{upload['filename']}")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
