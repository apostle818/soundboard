# CLAUDE.md

## Security & privacy guidelines

These come out of a security audit of this repo (Aug 2026) and should guide
any future change here.

### Secrets

- `SECRET_KEY` must come from the environment (`.env`, or the Portainer /
  systemd env) and must never have a code fallback (`os.urandom(...)` etc.).
  `app.py` already raises at startup if it is missing — keep that behaviour,
  don't "helpfully" generate one.
- Never hardcode a password, API key, or token in `app.py`, `manage.py`, or
  any test/fixture that resembles a real credential. The initial version of
  this app shipped a hardcoded `ADMIN_PASSWORD = "changeme123"` — it was
  replaced with per-user hashed passwords in `users.db`, but the old value is
  still visible in `git log -p` history. Git history is effectively
  permanent: assume anything ever committed is public, and rotate rather
  than "fix" if it happens again.
- `.env`, `users.db`, `sounds_db.json`, and `sounds/` are gitignored and
  dockerignored — keep it that way, and never `git add -f` around it.
- Pin every package that the app imports directly and relies on for security
  behaviour (auth, signing, crypto) in `requirements.txt`, even if it would
  otherwise arrive as a transitive dependency — see `Werkzeug` (pinned after
  it was found to be transitive-only) and do the same for `itsdangerous`,
  which `app.py` uses directly for token signing but which is currently only
  pulled in transitively via Flask.

### Debug mode / production posture

- `app.run(debug=...)` must never default to `True`. The Werkzeug debugger is
  a remote code execution console when reachable. Keep `debug_enabled()`
  opt-in via an explicit env var, and keep production on gunicorn (see
  `Dockerfile`/`docker-compose.yml`), which never touches `app.run()` at all.
- Don't add a `SOUNDBOARD_DEBUG`-style flag to the Docker/Portainer path.
  Debug mode is for `python app.py` on a workstation only.
- Run the container as the existing non-root `app` user; don't add anything
  to the `Dockerfile` that needs `USER root` at runtime.

### Uploads

- Audio uploads are validated by sniffing the file's actual bytes
  (`sniff_audio_extension`), not by trusting the client-supplied filename or
  `Content-Type`. Keep it that way for any new upload path — filename/MIME
  is a hint only, never the basis for what gets stored or how it's served.
  See `AUDIO_TYPES` for the full allowlist story.
- Stored filenames are always a generated UUID + the sniffed extension —
  never derive a stored filename from user input, to avoid path traversal.
- Keep `MAX_CONTENT_LENGTH` (`SOUNDBOARD_MAX_UPLOAD_MB`) set on any route
  that accepts a body, so a single upload can't fill the disk.
- `/sounds/<filename>` only serves extensions present in `AUDIO_TYPES` and
  sets `X-Content-Type-Options: nosniff`. Don't turn this into a general
  static file server.

### Dependencies

- `requirements.txt` / `requirements-dev.txt` pin every package. Re-check
  Flask, Werkzeug, gunicorn, python-dotenv, itsdangerous, and pytest for
  known CVEs and EOL status at least every few months, and whenever a
  dependency bump is made anyway — bump with a commit message that names the
  CVE/advisory, as in `b65fa27`.

### Authorization

- Every mutating route (`POST`/`PATCH`/`DELETE` under `/api/...`) must check
  `check_token(...)` server-side and return 401 on failure — never rely on
  the admin UI hiding a button. `GET /api/sounds` and sound playback stay
  public by design (this is a shared soundboard); don't accidentally widen
  that to the mutating routes or narrow it in a way that breaks the public
  read path without an explicit decision to do so.
