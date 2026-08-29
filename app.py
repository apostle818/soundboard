from flask import Flask, request, jsonify, send_from_directory, send_file
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import io
import json
import os
import sqlite3
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
    conn.commit()
    return conn

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

# --- Routes ---

@app.route("/")
def index():
    return send_file("static/index.html")

@app.route("/api/auth", methods=["POST"])
def auth():
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

    file     = request.files["file"]
    ext      = Path(file.filename).suffix or ".webm"
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

MIME_TYPES = {
    ".webm": "audio/webm",
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".m4a":  "audio/mp4",
}

@app.route("/sounds/<filename>")
def serve_sound(filename):
    mime = MIME_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")
    return send_from_directory(SOUNDS_DIR, filename, mimetype=mime)

def debug_enabled():
    """Whether the dev server should run with the Werkzeug debugger.

    The debugger is a remote code execution console, so it is opt-in via an
    explicit env var and never the default. Production serves through gunicorn
    (see Dockerfile) and does not reach this at all.
    """
    return os.environ.get("SOUNDBOARD_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

if __name__ == "__main__":
    app.run(debug=debug_enabled(), port=5000)
