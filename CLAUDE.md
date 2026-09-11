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

### Sweep (2026-09-11)

Re-verification pass plus one new fix. Re-checked line by line against the current `app.py`,
`static/index.html`, `Dockerfile`, `requirements.txt` and git history — everything closed by the
2026-08-31 and 2026-09-07 sweeps still holds: `SECRET_KEY` still has no fallback and raises
`RuntimeError` if unset/empty; `debug_enabled()` still requires the explicit `SOUNDBOARD_DEBUG` env
var against an allowlist of truthy strings, never a bare `True`; `MAX_CONTENT_LENGTH` still bounds
every request; `sniff_audio_extension()` still validates uploads by magic bytes, with the claimed
extension only ever a pre-filter; every mutating `/api/...` route still calls `check_token(...)`
server-side and 401s on failure; the security headers and CSP are unchanged and set on every
response; the Dockerfile still runs as non-root `app` (uid 1000) via gunicorn's `gthread` workers,
never `flask run`; and the 2026-09-07 `escHtml(JSON.stringify(c))` fix on the category-pill
`onclick` is still in place in `static/index.html:948` — no other dynamic value reaches an
attribute or `innerHTML` write unescaped (`s.id` is a server-generated UUID, safe by construction;
every other server-supplied string goes through `escHtml`).

- `pip-audit -r requirements.txt`: **no known vulnerabilities**, versions unchanged from
  2026-09-07 (Flask 3.1.3, Werkzeug 3.1.8, gunicorn 23.0.0, python-dotenv 1.2.3, itsdangerous
  2.2.0; transitively blinker 1.9.0, click 8.5.0, jinja2 3.1.6, markupsafe 3.0.3 — also clean).
  Checked PyPI directly: all five pinned packages are already at the newest release in their
  line (Flask has no 3.1.4, Werkzeug's newest is still 3.1.8, python-dotenv and itsdangerous are
  both at their latest overall). `gunicorn` has a newer `26.2.0` upstream but that is a
  major-version jump with no CVE behind the pinned `23.0.0` — not bumped, same reasoning as
  2026-09-07. No dependency changes made.
- Re-checked the two specific CVEs this file has discussed before: CVE-2026-27205 (Flask info
  disclosure, fixed above 3.1.2) and CVE-2026-21860 (Werkzeug `safe_join` Windows path traversal,
  fixed in 3.1.5) — both assessments still hold at the currently pinned 3.1.3/3.1.8, and
  `pip-audit`'s clean result against those exact pins is independent confirmation.
- `rate_limited()`'s SQLite-backed per-IP counter: re-read `users_conn()`/`rate_limited()` —
  every call opens a fresh connection against the on-disk `USERS_DB` path (not an in-process
  dict), so the count is inherently shared by construction across however many gunicorn worker
  processes read and write that same file. Still correct.
- Re-scanned full git history (`git log -p --all` across all 38 commits, plus a `-S"changeme123"`
  search) for secrets: nothing beyond the already-known pre-`3fede78` `ADMIN_PASSWORD =
  "changeme123"` placeholder in `app.py`/`.env.example` (never a real credential, superseded by
  the current per-user hashed `users.db` design). No `.env`, key, or certificate file ever
  committed.
- Ran the full `pytest` suite: 86 passed before this pass's change, 88 after (two new tests
  added with the fix below).

**Fixed — username enumeration via login response timing.** `/api/auth` returned as soon as the
SQLite lookup found no row for an unknown username, but for a known username with the wrong
password it additionally ran `check_password_hash`, which costs real time under werkzeug's default
scrypt hashing (measured: roughly 100 ms per call on this machine, vs. sub-millisecond for the
lookup alone). That gap is large enough to remotely distinguish "no such user" from "wrong
password" by timing alone, letting an attacker enumerate valid usernames on a route whose error
message is otherwise identical (`"Invalid credentials"` either way) and which is protected only by
a per-IP — not per-account — rate limit, so enumeration itself isn't rate-limited by username.
Fixed by checking a dummy password hash (`_DUMMY_PASSWORD_HASH`, generated once at import from a
random value, never persisted, never a real credential) on the "no such user" path, so both paths
call `check_password_hash` exactly once and take comparable time. This does not touch either
documented accepted tradeoff on this route (the per-IP rate limiter, or the stateless tokens) —
those are unrelated and were left exactly as they were. Regression tests:
`tests/test_auth_timing.py` (asserts the call happens on both paths, functionally, rather than
asserting on wall-clock timing — a timing assertion would be flaky under CI load).

### Suspicious content check

No `AGENTS.md` or similar file exists anywhere in this repo (re-checked this pass), and no code
comment, commit message, or README content attempts to redirect what an agent working here should
do. Nothing found in this sweep or either of the prior two.
