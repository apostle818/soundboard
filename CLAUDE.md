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
- **Every mutating route (`POST`/`PATCH`/`DELETE` under `/api/...`) must check `check_token(...)`
  server-side and return 401 on failure** — never rely on the admin UI hiding a button. `GET
  /api/sounds` and sound playback stay public by design (see the tradeoff below); don't
  accidentally widen that exemption to a mutating route, or narrow the public read path without
  an explicit decision to do so.
- **Re-check pinned dependencies (Flask, Werkzeug, gunicorn, python-dotenv, itsdangerous, pytest)
  for CVEs and EOL status at least every few months**, not only when a headline CVE prompts it —
  bump with a commit message that names the advisory, as in `b65fa27`.

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

### Sweep (2026-09-07)

Re-verification pass plus one new fix. Re-checked line by line against the current `app.py`,
`static/index.html`, `Dockerfile`, `requirements.txt` and git history rather than trusting the
2026-08-31 notes above — all of the "What this sweep added" and "Standing practices" items still
hold as described: `SECRET_KEY` still has no fallback and still raises `RuntimeError`; the
Werkzeug debugger is still opt-in only via `SOUNDBOARD_DEBUG`; `MAX_CONTENT_LENGTH` still bounds
every request; uploads are still validated by `sniff_audio_extension()` (magic bytes, not
filename); every mutating `/api/...` route still calls `check_token(...)` server-side; the
security headers and CSP are unchanged and still set on every response; the Docker image still
runs as non-root `app` (uid 1000) via gunicorn, never `flask run`.

- **Fixed — stored HTML/attribute injection in the category-pill renderer**
  (`static/index.html`, the `renderGrid`/pills code). The pill button's `onclick` attribute
  embedded a category name via `` onclick="setCategory(${JSON.stringify(c)})" `` — `JSON.stringify`
  produces JavaScript-safe quoting (`\"`), not HTML-safe quoting, and this was the one spot in the
  file where user-controlled text reached `innerHTML` without going through `escHtml()` first. A
  category name containing a literal `"` (settable by anyone holding an auth token, since
  `POST /api/sounds`/`PATCH /api/sounds/<id>` accept an unrestricted `category` string) would close
  the attribute early and let the rest of the string inject arbitrary markup or a new event handler
  into a page every anonymous visitor loads — and the CSP's `'unsafe-inline'` concession for
  `script-src` (needed for the page's legitimate inline `onclick`s) means an injected inline handler
  would have executed rather than being blocked. Every other dynamic value in this file already
  went through `escHtml()`; this one only went through `JSON.stringify()`. Fixed by wrapping it —
  `` onclick="setCategory(${escHtml(JSON.stringify(c))})" `` — so an embedded `"` becomes `&quot;`
  instead of terminating the attribute. Regression guard: `tests/test_frontend_escaping.py` (asserts
  the vulnerable pattern is gone and the fixed one is present, since this file has no build step or
  JS test harness by design).
- Re-ran `pip-audit` against `requirements.txt`: clean, no known vulnerabilities in Flask 3.1.3,
  Werkzeug 3.1.8, gunicorn 23.0.0, python-dotenv 1.2.3, or itsdangerous 2.2.0. Checked the 2026
  Flask/Werkzeug CVEs specifically: CVE-2026-27205 (Flask info disclosure) affects <=3.1.2, already
  above it; CVE-2026-21860 (Werkzeug `safe_join` Windows device-name traversal) is fixed in 3.1.5,
  already above it (and Windows-only regardless — this app deploys in a Linux container).
  CVE-2026-40035 ("Flask debug mode RCE") turned out to be misfiled against an unrelated tool
  (`obsidianforensics/unfurl`'s own config parsing), not Flask or this app — checked
  `debug_enabled()` against that bug's actual shape (a truthy-string config parse) anyway; it
  already uses an explicit allowlist (`{"1","true","yes","on"}`), not "any non-empty string enables
  debug". No dependency version bump made — nothing here needed one.
  `gunicorn` has a newer `26.2.0` release upstream; not bumped, since it is a major-version jump
  with no CVE behind it and `pip-audit` is clean on 23.0.0 — re-evaluate next time an actual
  advisory names it.
- Ran the full `pytest` suite (86 tests after the new regression test): all green.
- Re-scanned full git history (`git log --all -p`) for hardcoded secrets: nothing beyond what the
  prior sweep already knew about — a pre-`3fede78`, long-removed `ADMIN_PASSWORD = "changeme123"`
  placeholder (never a real credential, and superseded by the current `manage.py`/SQLite
  argon2-hashed-user design). No `.env`, key, or certificate file ever committed.
- No `AGENTS.md` or similar file found this pass either, and nothing in code comments, commit
  messages, or docs attempts to redirect an agent's behavior.

### Suspicious content check

No `AGENTS.md` or similar file exists anywhere in this repo, and no code comment, commit message,
or README content attempts to redirect what an agent working here should do. Nothing found in
this sweep or the prior one.
