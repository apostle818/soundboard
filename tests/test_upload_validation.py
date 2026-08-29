import io

import pytest

from conftest import M4A_BYTES, MP3_BYTES, OGG_BYTES, WAV_BYTES, WEBM_BYTES

MKV_BYTES = (b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x23\x42\x86\x81\x01"
             b"\x42\x82\x88matroska" + b"\x00" * 32)
PHP_BYTES = b"<?php system($_GET['c']); ?>"
HTML_BYTES = b"<html><script>alert(1)</script></html>"
ELF_BYTES = b"\x7fELF\x02\x01\x01" + b"\x00" * 64
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 64


def upload(client, token, data, filename):
    return client.post(
        "/api/sounds",
        data={"token": token, "name": "Clip", "category": "General",
              "file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


@pytest.mark.parametrize("data,filename,expected", [
    (WAV_BYTES,  "clip.wav",  ".wav"),
    (MP3_BYTES,  "clip.mp3",  ".mp3"),
    (OGG_BYTES,  "clip.ogg",  ".ogg"),
    (M4A_BYTES,  "clip.m4a",  ".m4a"),
    (WEBM_BYTES, "clip.webm", ".webm"),
])
def test_accepts_each_allowed_audio_container(client, token, data, filename, expected):
    resp = upload(client, token, data, filename)
    assert resp.status_code == 201
    assert resp.get_json()["filename"].endswith(expected)


def test_stored_extension_comes_from_content_not_filename(client, token):
    """A real wav announced as .mp3 is stored — and served — as a wav."""
    entry = upload(client, token, WAV_BYTES, "clip.mp3").get_json()
    assert entry["filename"].endswith(".wav")
    assert client.get(f"/sounds/{entry['filename']}").mimetype == "audio/wav"


def test_mp3_without_id3_tag_is_accepted(client, token):
    resp = upload(client, token, b"\xff\xfb\x90\x00" + b"\x00" * 128, "clip.mp3")
    assert resp.status_code == 201
    assert resp.get_json()["filename"].endswith(".mp3")


def test_mp3_with_id3_tag_larger_than_the_sniff_window_is_accepted(client, token):
    # 8192-byte tag (e.g. cover art) pushes the frame sync past SNIFF_BYTES.
    size = 8192
    syncsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F,
                      (size >> 7) & 0x7F, size & 0x7F])
    data = b"ID3\x03\x00\x00" + syncsafe + b"\x00" * size + b"\xff\xfb\x90\x00"
    resp = upload(client, token, data, "clip.mp3")
    assert resp.status_code == 201
    assert resp.get_json()["filename"].endswith(".mp3")


def test_id3_header_wrapping_non_audio_is_rejected(client, token):
    data = b"ID3\x03\x00\x00\x00\x00\x00\x00" + PHP_BYTES
    assert upload(client, token, data, "clip.mp3").status_code == 400


@pytest.mark.parametrize("data,filename", [
    (PHP_BYTES,  "shell.mp3"),
    (HTML_BYTES, "page.wav"),
    (ELF_BYTES,  "payload.ogg"),
    (ZIP_BYTES,  "archive.m4a"),
    (MKV_BYTES,  "video.webm"),
    (b"",        "empty.wav"),
    (b"RIFF" + b"\x00" * 32, "not-really.wav"),
])
def test_rejects_non_audio_content(client, token, data, filename):
    resp = upload(client, token, data, filename)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


@pytest.mark.parametrize("filename", ["shell.php", "payload.exe", "notes.txt", "x.html"])
def test_rejects_disallowed_extension_even_with_real_audio_bytes(client, token, filename):
    resp = upload(client, token, MP3_BYTES, filename)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_rejected_upload_leaves_no_file_and_no_db_entry(client, token, soundboard):
    assert upload(client, token, PHP_BYTES, "shell.mp3").status_code == 400
    assert list(soundboard.SOUNDS_DIR.iterdir()) == []
    assert client.get("/api/sounds").get_json() == []


@pytest.mark.parametrize("filename", ["", "blob", "recording"])
def test_upload_without_an_extension_falls_back_to_content(client, token, filename):
    resp = upload(client, token, WAV_BYTES, filename)
    assert resp.status_code == 201
    assert resp.get_json()["filename"].endswith(".wav")


@pytest.mark.parametrize("filename", ["", "blob"])
def test_upload_without_an_extension_still_rejects_non_audio(client, token, filename):
    assert upload(client, token, PHP_BYTES, filename).status_code == 400


def test_serve_rejects_unknown_extension(client, soundboard):
    (soundboard.SOUNDS_DIR / "legacy.php").write_bytes(PHP_BYTES)
    assert client.get("/sounds/legacy.php").status_code == 404


def test_served_sound_sets_nosniff(client, token):
    entry = upload(client, token, WAV_BYTES, "clip.wav").get_json()
    resp = client.get(f"/sounds/{entry['filename']}")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


# Header shapes real encoders and browsers actually emit.
REAL_HEADERS = {
    ".webm": bytes.fromhex("1a45dfa39f4286810142f7810142f2810442f381084282847765626d42878102"),
    ".m4a":  bytes.fromhex("0000001c6674797069736f6d0000020069736f6d69736f326d703431"),   # Safari
    ".ogg":  bytes.fromhex("4f67675300020000000000000000") + b"\x00" * 40,
    ".wav":  b"RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00\x44\xac\x00\x00"
             + b"\x00" * 20,
    ".mp3":  b"ID3\x03\x00\x00" + _syncsafe(1277) + b"\x00" * 1277 + b"\xff\xfb\x90\x64",
}


@pytest.mark.parametrize("expected,data", sorted(REAL_HEADERS.items()))
def test_accepts_real_encoder_headers(client, token, expected, data):
    resp = upload(client, token, data, "recording" + expected)
    assert resp.status_code == 201
    assert resp.get_json()["filename"].endswith(expected)


def test_accepts_id3v24_tag_with_footer(client, token):
    size = 500
    data = (b"ID3\x04\x00\x10" + _syncsafe(size) + b"\x00" * size
            + b"3DI\x04\x00\x10" + _syncsafe(size) + b"\xff\xfb\x90\x64")
    assert upload(client, token, data, "clip.mp3").status_code == 201


@pytest.mark.parametrize("data", [
    b"\x00\x00\x00\x1cftypheic" + b"\x00" * 16,      # HEIC image, also an ftyp box
    b"\xff\xd8\xff\xe0" + b"\x00" * 32,              # JPEG: 0xff start, but no frame sync
    b"%PDF-1.4\n" + b"\x00" * 32,
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
])
def test_rejects_lookalike_binaries(client, token, data):
    assert upload(client, token, data, "clip.mp3").status_code == 400
