# CLAUDE.md

## Security

House rules from a repo security sweep on 2026-08-31, run after an earlier pass on this repo
(`claude/flask-soundboard-security-2kdzfn`, merged as `3fede78`) had already closed the biggest
issues: a required `SECRET_KEY` with no generated fallback, the Werkzeug debugger off by default,
a request body size cap, and content-sniffed upload validation (extension is a hint only; the
stored extension comes from the file's magic bytes, checked against an allowlist). Read `app.py`
top-to-bottom before assuming something below still needs fixing — it is a single ~350-line file
and stays that way on purpose.

### What this sweep added

- **`/api/auth` is now rate-limited per IP** (`rate_limited()` in `app.py`, backed by a SQLite
  table so the count holds across gunicorn's multiple worker processes, not just one). Defaults:
  10 attempts / 5 minutes, tunable via `SOUNDBOARD_AUTH_RATE_LIMIT` /
  `SOUNDBOARD_AUTH_RATE_WINDOW`. Before this, the login endpoint had no throttle at all.
- **`itsdangerous` is now pinned explicitly** in `requirements.txt`. `app.py` imports it directly
  for `URLSafeTimedSerializer` — the entire auth-token mechanism — but it was previously present
  only as a transitive dependency of Flask, so a Flask-only audit could resolve a different
  `itsdangerous` version than what's actually running. Security-sensitive direct imports get
  their own pin even when a parent package would drag them in anyway.
- **Security response headers** are set for every response (`set_security_headers()` in `app.py`):
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  a restrictive `Permissions-Policy`, and a `Content-Security-Policy`. The CSP keeps
  `'unsafe-inline'` for `script-src`/`style-src` because `static/index.html` is a single
  hand-written file that leans on inline `onclick="..."` handlers and an inline `<script>` block —
  a strict CSP without it would break the UI outright. What the CSP still buys: no framing
  (`frame-ancestors 'none'`), no plugins/objects, no `<base>` hijacking, and script/connect/media
  origins locked to this app plus the two Google Fonts hosts the page already loads from
  (`media-src` additionally allows `blob:` for the in-browser recording preview).

### Standing practices to preserve

- **Every new upload path must go through `sniff_audio_extension()`.** The client-supplied
  filename is a hint only — never trust `file.filename`'s extension for what gets stored or how
  it's served. `serve_sound()` re-derives the MIME type from the stored extension against the
  `AUDIO_TYPES` allowlist; anything else 404s rather than being served back to a browser.
- **`SECRET_KEY` has no fallback and must not get one.** `app.py` raises `RuntimeError` at import
  time if it's unset or empty. Do not reintroduce `os.urandom()` as a default — that failure mode
  (silently invalidating every issued token on restart) is exactly what the check exists to catch.
- **The Werkzeug debugger stays opt-in.** `debug_enabled()` only returns `True` via the explicit
  `SOUNDBOARD_DEBUG` env var; `app.run(debug=...)` must keep reading from that function, never a
  literal `True`. Production runs through gunicorn (`Dockerfile` `CMD`) and never reaches
  `app.run()` at all — keep it that way; don't let the dev server become the production path.
- **New free-text rendered into `static/index.html` must go through `escHtml()`.** Every current
  `innerHTML` write of user-controlled data (`name`, `category`, keybinding labels) is escaped;
  keep that pattern for anything new — the CSP's `'unsafe-inline'` concession means it is not a
  backstop for a missed escape.
- **`MAX_CONTENT_LENGTH` bounds every request, not just uploads.** If a route ever needs to accept
  something larger, raise it deliberately and explain why in a comment next to `MAX_UPLOAD_MB`,
  don't just remove the cap.
- **Docker runs as a non-root `app` user** (`Dockerfile`) and production is gunicorn with
  `gthread` workers, not `flask run`. Preserve both if the Dockerfile changes.
- **Auth is a single-table SQLite allowlist, not a role system.** `manage.py` is the only supported
  way to create/remove users; there's no self-service signup and no in-app password reset by
  design — a small self-hosted single-family/small-group tool doesn't need one, but don't wire one
  up without also adding rate limiting and lockout to match.

### Known, accepted tradeoffs (documented, not "fix this")

- **Auth tokens are stateless (`itsdangerous`-signed, 24h TTL) with no server-side revocation.**
  There is no session table, so there is no way to force-expire a token before it ages out short
  of rotating `SECRET_KEY` (which invalidates *every* issued token, not just one). Acceptable for
  the current scale (a handful of trusted household/friend admins); would need a real session
  store to support per-user logout/revocation.
- **The rate limiter is per-IP, not per-account**, and reads `request.remote_addr` directly. If
  this is ever deployed behind a reverse proxy that doesn't preserve the real client IP, every
  request will appear to come from the proxy and share one limit bucket — effectively disabling
  the limiter for distinct attackers while still capping legitimate traffic. If that becomes the
  deployment shape, this needs a trusted-hops-aware `X-Forwarded-For` parse (see how
  `TRUSTED_PROXY_HOPS` is handled in sibling repos), not a blind trust of the header.
- **`GET /api/sounds` and `GET /sounds/<filename>` are unauthenticated by design** — this is a
  soundboard meant to be shared with visitors who don't have accounts. Don't "fix" this without
  confirming that's actually a requirements change, not a bug.

### Suspicious content check

No `AGENTS.md` or similar file exists anywhere in this repo, and no code comment, commit message,
or README content attempts to redirect what an agent working here should do. Nothing found in
this sweep or the prior one.
