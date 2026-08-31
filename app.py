from flask import Flask, request, jsonify, send_from_directory, send_file
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import io
import json
import os
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path

load_dotenv()

app = Flask(__name__, static_folder='static')

# --- Config ---
SOUNDS_DIR = Path(os.environ.get("SOUNDBOARD_SOUNDS_DIR", "sounds"))
DB_FILE    = Path(os.environ.get("SOUNDBOARD_DB_FILE",    "sounds_db.json"))
USERS_DB   = Path(os.environ.get("SOUNDBOARD_USERS_DB",   "users.db"))
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Generate one with `openssl rand -hex 32` and put it "
        "in the environment (or .env) before starting the app. Refusing to start with "
        "a generated key: it would silently invalidate every auth token on restart."
    )
TOKEN_MAX_AGE = 86400  # 24 h

# Cap request bodies so an upload cannot fill the disk. Applies to every route.
MAX_UPLOAD_MB = int(os.environ.get("SOUNDBOARD_MAX_UPLOAD_MB", "25"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Per-IP cap on /api/auth attempts, so the login form cannot be brute-forced
# at line rate. Backed by SQLite (see rate_limited() below) rather than an
# in-process counter so it holds across gunicorn's worker processes.
AUTH_RATE_LIMIT  = int(os.environ.get("SOUNDBOARD_AUTH_RATE_LIMIT",  "10"))   # attempts
AUTH_RATE_WINDOW = int(os.environ.get("SOUNDBOARD_AUTH_RATE_WINDOW", "300"))  # seconds

signer = URLSafeTimedSerializer(SECRET_KEY)
SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)
USERS_DB.parent.mkdir(parents=True, exist_ok=True)

# --- Users DB ---
def users_conn():
    conn = sqlite3.connect(USERS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS auth_attempts (
        ip           TEXT NOT NULL,
        attempted_at REAL NOT NULL
    )""")
    conn.commit()
    return conn

def rate_limited(ip):
    """True if `ip` has already made AUTH_RATE_LIMIT /api/auth attempts within
    the last AUTH_RATE_WINDOW seconds. Also records the current attempt (when
    not already limited) and prunes rows outside the window, so the table
    stays small and every gunicorn worker sees the same count.
    """
    now  = time.time()
    cutoff = now - AUTH_RATE_WINDOW
    conn = users_conn()
    conn.execute("DELETE FROM auth_attempts WHERE attempted_at < ?", (cutoff,))
    count = conn.execute(
        "SELECT COUNT(*) FROM auth_attempts WHERE ip = ? AND attempted_at >= ?",
        (ip, cutoff),
    ).fetchone()[0]
    limited = count >= AUTH_RATE_LIMIT
    if not limited:
        conn.execute("INSERT INTO auth_attempts (ip, attempted_at) VALUES (?, ?)", (ip, now))
    conn.commit()
    conn.close()
    return limited

def check_token(data=None):
    if data is None:
        data = request.get_json(silent=True) or {}
    token = data.get("token") or request.form.get("token")
    if not token:
        return None
    try:
        payload = signer.loads(token, max_age=TOKEN_MAX_AGE)
        return payload.get("user")
    except (BadSignature, SignatureExpired):
        return None

# --- Sounds DB helpers ---
def load_db():
    if not DB_FILE.exists():
        DB_FILE.write_text(json.dumps([]))
    return json.loads(DB_FILE.read_text())

def save_db(data):
    DB_FILE.write_text(json.dumps(data, indent=2))

# --- Upload validation ---
# The extension a sound is stored under is decided by sniffing the file's magic
# bytes; the client-supplied filename is only ever a hint. Nothing outside this
# table can be stored or served.
AUDIO_TYPES = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".m4a":  "audio/mp4",
    ".webm": "audio/webm",
}
SNIFF_BYTES = 4096
EBML_MAGIC = b"\x1a\x45\xdf\xa3"
# ISO-BMFF brands that carry audio we are willing to serve as audio/mp4.
MP4_BRANDS = {b"M4A ", b"M4B ", b"mp41", b"mp42", b"isom", b"iso2", b"dash"}

def _ebml_doctype(head):
    """Read the DocType of an EBML header, so matroska cannot pass as webm."""
    marker = head.find(b"\x42\x82", 0, 64)
    if marker < 0 or len(head) <= marker + 2:
        return None
    size_byte = head[marker + 2]
    if not size_byte & 0x80:       # real headers use a single-byte length here
        return None
    length = size_byte & 0x7F
    return head[marker + 3:marker + 3 + length]

def _has_mpeg_frame_sync(data):
    if len(data) < 2 or data[0] != 0xFF or data[1] & 0xE0 != 0xE0:
        return False
    version = (data[1] >> 3) & 0x03
    layer   = (data[1] >> 1) & 0x03
    return version != 0x01 and layer != 0x00   # both values are reserved

def _is_mp3(head, stream):
    if head[:3] != b"ID3":
        return _has_mpeg_frame_sync(head)
    if len(head) < 10:
        return False
    size = 0
    for byte in head[6:10]:
        if byte & 0x80:            # ID3 sizes are syncsafe: high bit always clear
            return False
        size = (size << 7) | byte
    offset = 10 + size + (10 if head[5] & 0x10 else 0)   # 0x10 = footer present
    if offset + 2 <= len(head):
        return _has_mpeg_frame_sync(head[offset:offset + 2])
    stream.seek(offset)            # tag runs past the sniffed window
    return _has_mpeg_frame_sync(stream.read(2))

def sniff_audio_extension(stream):
    """Return the allowlisted extension matching the stream's actual content.

    Returns None when the bytes are not one of the audio containers we accept.
    The stream is rewound before returning either way.
    """
    try:
        head = stream.read(SNIFF_BYTES)
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return ".wav"
        if head[:4] == b"OggS":
            return ".ogg"
        if head[4:8] == b"ftyp" and head[8:12] in MP4_BRANDS:
            return ".m4a"
        if head[:4] == EBML_MAGIC and _ebml_doctype(head) == b"webm":
            return ".webm"
        if _is_mp3(head, stream):
            return ".mp3"
        return None
    finally:
        stream.seek(0)

# --- Errors ---
@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return jsonify({"error": f"File too large (max {MAX_UPLOAD_MB} MB)"}), 413

# --- Security headers ---
# The frontend is one hand-written HTML file that relies on inline
# onclick="..." handlers and an inline <script> block (see static/index.html),
# so a strict CSP without 'unsafe-inline' would break every button on the
# page. This policy keeps that working while still doing real work: it stops
# the page from being framed, blocks plugins/objects, and restricts script,
# connect and media origins to this app plus the two Google Fonts hosts the
# page already loads from.
_CSP = ("default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # blob: is needed for the in-browser recording preview (<audio> fed
        # from a MediaRecorder blob via URL.createObjectURL — see static/index.html).
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'")

@app.after_request
def set_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy",
                             "microphone=(self), camera=(), geolocation=()")
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    return resp

# --- Routes ---

@app.route("/")
def index():
    return send_file("static/index.html")

@app.route("/api/auth", methods=["POST"])
def auth():
    if rate_limited(request.remote_addr or "unknown"):
        resp = jsonify({"error": f"Too many login attempts. Try again in "
                                  f"{AUTH_RATE_WINDOW // 60} minutes."})
        resp.headers["Retry-After"] = str(AUTH_RATE_WINDOW)
        return resp, 429

    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    conn = users_conn()
    row  = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if not row or not check_password_hash(row[0], password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = signer.dumps({"user": username})
    return jsonify({"token": token, "username": username})

@app.route("/api/sounds", methods=["GET"])
def get_sounds():
    return jsonify(load_db())

@app.route("/api/sounds", methods=["POST"])
def add_sound():
    if not check_token():
        return jsonify({"error": "Unauthorized"}), 401

    name      = request.form.get("name", "Untitled").strip()
    category  = request.form.get("category", "General").strip()
    sound_id  = str(uuid.uuid4())

    if "file" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    file = request.files["file"]

    # The filename is a hint only: reject anything claiming an extension we do
    # not serve, then let the file's own bytes decide what it is stored as.
    claimed = Path(file.filename or "").suffix.lower()
    if claimed and claimed not in AUDIO_TYPES:
        return jsonify({"error": f"Unsupported file extension '{claimed}'. "
                                 f"Accepted: {', '.join(sorted(AUDIO_TYPES))}"}), 400

    ext = sniff_audio_extension(file.stream)
    if ext is None:
        return jsonify({"error": "File is not recognisable audio. "
                                 f"Accepted: {', '.join(sorted(AUDIO_TYPES))}"}), 400

    filename = f"{sound_id}{ext}"
    file.save(SOUNDS_DIR / filename)

    db    = load_db()
    entry = {"id": sound_id, "name": name, "category": category, "filename": filename}
    db.append(entry)
    save_db(db)
    return jsonify(entry), 201

@app.route("/api/sounds/<sound_id>", methods=["PATCH"])
def update_sound(sound_id):
    data = request.get_json(silent=True) or {}
    if not check_token(data):
        return jsonify({"error": "Unauthorized"}), 401

    db    = load_db()
    entry = next((s for s in db if s["id"] == sound_id), None)
    if not entry:
        return jsonify({"error": "Not found"}), 404

    if "name" in data:
        entry["name"]     = data["name"].strip()     or entry["name"]
    if "category" in data:
        entry["category"] = data["category"].strip() or entry["category"]

    save_db(db)
    return jsonify(entry)

@app.route("/api/sounds/<sound_id>", methods=["DELETE"])
def delete_sound(sound_id):
    data = request.get_json(silent=True) or {}
    if not check_token(data):
        return jsonify({"error": "Unauthorized"}), 401

    db    = load_db()
    entry = next((s for s in db if s["id"] == sound_id), None)
    if not entry:
        return jsonify({"error": "Not found"}), 404

    (SOUNDS_DIR / entry["filename"]).unlink(missing_ok=True)
    save_db([s for s in db if s["id"] != sound_id])
    return jsonify({"ok": True})

@app.route("/api/backup", methods=["POST"])
def backup():
    data = request.get_json(silent=True) or {}
    if not check_token(data):
        return jsonify({"error": "Unauthorized"}), 401

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if DB_FILE.exists():
            zf.write(DB_FILE, "sounds_db.json")
        for f in sorted(SOUNDS_DIR.iterdir()):
            if f.is_file():
                zf.write(f, f"sounds/{f.name}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="soundboard-backup.zip")

@app.route("/sounds/<filename>")
def serve_sound(filename):
    mime = AUDIO_TYPES.get(Path(filename).suffix.lower())
    if mime is None:
        # Only allowlisted audio can be stored, so anything else here is junk
        # left by an older upload path — never hand it back to a browser.
        return jsonify({"error": "Not found"}), 404
    resp = send_from_directory(SOUNDS_DIR, filename, mimetype=mime)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

def debug_enabled():
    """Whether the dev server should run with the Werkzeug debugger.

    The debugger is a remote code execution console, so it is opt-in via an
    explicit env var and never the default. Production serves through gunicorn
    (see Dockerfile) and does not reach this at all.
    """
    return os.environ.get("SOUNDBOARD_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

if __name__ == "__main__":
    app.run(debug=debug_enabled(), port=5000)
