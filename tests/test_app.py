import io
import json
import zipfile

from conftest import WAV_BYTES


def upload(client, token, data=WAV_BYTES, filename="clip.wav", name="Clip"):
    return client.post(
        "/api/sounds",
        data={
            "token": token,
            "name": name,
            "category": "General",
            "file": (io.BytesIO(data), filename),
        },
        content_type="multipart/form-data",
    )


def test_index_served(client):
    assert client.get("/").status_code == 200


def test_auth_rejects_bad_password(client):
    resp = client.post("/api/auth", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_auth_rejects_unknown_user(client):
    resp = client.post("/api/auth", json={"username": "mallory", "password": "hunter2"})
    assert resp.status_code == 401


def test_auth_returns_token(client, token):
    assert token


def test_sounds_list_starts_empty(client):
    assert client.get("/api/sounds").get_json() == []


def test_upload_requires_token(client):
    resp = client.post(
        "/api/sounds",
        data={"name": "Clip", "file": (io.BytesIO(WAV_BYTES), "clip.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401


def test_upload_rejects_bad_token(client):
    assert upload(client, "not-a-real-token").status_code == 401


def test_upload_requires_a_file(client, token):
    resp = client.post("/api/sounds", data={"token": token, "name": "Clip"},
                       content_type="multipart/form-data")
    assert resp.status_code == 400


def test_upload_stores_and_lists_sound(client, token, soundboard):
    resp = upload(client, token)
    assert resp.status_code == 201
    entry = resp.get_json()
    assert entry["name"] == "Clip"
    assert entry["category"] == "General"
    assert (soundboard.SOUNDS_DIR / entry["filename"]).exists()
    assert client.get("/api/sounds").get_json() == [entry]


def test_uploaded_sound_is_served_back(client, token):
    entry = upload(client, token).get_json()
    resp = client.get(f"/sounds/{entry['filename']}")
    assert resp.status_code == 200
    assert resp.mimetype == "audio/wav"
    assert resp.data == WAV_BYTES


def test_patch_requires_token(client, token):
    entry = upload(client, token).get_json()
    resp = client.patch(f"/api/sounds/{entry['id']}", json={"name": "Nope"})
    assert resp.status_code == 401


def test_patch_updates_name_and_category(client, token):
    entry = upload(client, token).get_json()
    resp = client.patch(f"/api/sounds/{entry['id']}",
                        json={"token": token, "name": "Renamed", "category": "Memes"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Renamed"
    assert client.get("/api/sounds").get_json()[0]["category"] == "Memes"


def test_patch_unknown_sound_is_404(client, token):
    resp = client.patch("/api/sounds/does-not-exist", json={"token": token, "name": "x"})
    assert resp.status_code == 404


def test_delete_requires_token(client, token):
    entry = upload(client, token).get_json()
    assert client.delete(f"/api/sounds/{entry['id']}").status_code == 401


def test_delete_removes_entry_and_file(client, token, soundboard):
    entry = upload(client, token).get_json()
    resp = client.delete(f"/api/sounds/{entry['id']}", json={"token": token})
    assert resp.status_code == 200
    assert client.get("/api/sounds").get_json() == []
    assert not (soundboard.SOUNDS_DIR / entry["filename"]).exists()


def test_backup_requires_token(client):
    assert client.post("/api/backup", json={}).status_code == 401


def test_backup_zips_db_and_sounds(client, token):
    entry = upload(client, token).get_json()
    resp = client.post("/api/backup", json={"token": token})
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
        assert "sounds_db.json" in names
        assert f"sounds/{entry['filename']}" in names
        assert json.loads(zf.read("sounds_db.json"))[0]["id"] == entry["id"]
