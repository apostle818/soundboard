from flask import Flask, request, jsonify, send_from_directory, send_file
from dotenv import load_dotenv
import json
import os
import uuid
from pathlib import Path

load_dotenv()

app = Flask(__name__, static_folder='static')

# --- Config ---
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SOUNDS_DIR = Path("sounds")
DB_FILE = Path("sounds_db.json")
SOUNDS_DIR.mkdir(exist_ok=True)

# --- DB helpers ---
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
    data = request.json or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"ok": True})

@app.route("/api/sounds", methods=["GET"])
def get_sounds():
    return jsonify(load_db())

@app.route("/api/sounds", methods=["POST"])
def add_sound():
    password = request.form.get("password") or (request.json or {}).get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 401

    name = request.form.get("name", "Untitled").strip()
    category = request.form.get("category", "General").strip()
    sound_id = str(uuid.uuid4())

    if "file" in request.files:
        file = request.files["file"]
        ext = Path(file.filename).suffix or ".webm"
        filename = f"{sound_id}{ext}"
        file.save(SOUNDS_DIR / filename)
    else:
        return jsonify({"error": "No audio file provided"}), 400

    db = load_db()
    entry = {"id": sound_id, "name": name, "category": category, "filename": filename}
    db.append(entry)
    save_db(db)
    return jsonify(entry), 201

@app.route("/api/sounds/<sound_id>", methods=["DELETE"])
def delete_sound(sound_id):
    data = request.json or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "Unauthorized"}), 401

    db = load_db()
    entry = next((s for s in db if s["id"] == sound_id), None)
    if not entry:
        return jsonify({"error": "Not found"}), 404

    (SOUNDS_DIR / entry["filename"]).unlink(missing_ok=True)
    db = [s for s in db if s["id"] != sound_id]
    save_db(db)
    return jsonify({"ok": True})

MIME_TYPES = {
    '.webm': 'audio/webm',
    '.mp3':  'audio/mpeg',
    '.wav':  'audio/wav',
    '.ogg':  'audio/ogg',
    '.m4a':  'audio/mp4',
}

@app.route("/sounds/<filename>")
def serve_sound(filename):
    mime = MIME_TYPES.get(Path(filename).suffix.lower(), 'application/octet-stream')
    return send_from_directory(SOUNDS_DIR, filename, mimetype=mime)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
