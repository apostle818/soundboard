# Soundboard

A self-hosted web soundboard — record or upload quotes, share with others.

## Structure

```
soundboard/
├── app.py              ← Flask backend
├── sounds_db.json      ← Auto-created on first run (sound metadata)
├── sounds/             ← Auto-created on first run (audio files)
├── static/
│   └── index.html      ← Frontend (served by Flask)
└── README.md
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your admin password

Copy the example config and edit it:

```bash
cp .env.example .env
nano .env   # set ADMIN_PASSWORD=yourpassword
```

`.env` is gitignored — it will never be overwritten by `git pull`.

### 3. Run

```bash
python app.py
```

App will be at: **http://localhost:5000**

### 4. Share with others

Point them to your server's IP/domain. If running on a server:

```bash
# Run on all interfaces so others can reach it
python app.py --host 0.0.0.0
```

Or for production, put it behind **nginx + gunicorn**:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Usage

### Visitors

- Click any tile to play; click again (or press `Space`) to stop
- A floating **now-playing dock** shows name, duration, and progress while audio plays
- Star a tile (★) to add it to **Favorites**, then filter to favorites with the pill
- **Drag the grip handle** (top-right corner of a tile, visible on hover) to reorder
- Search and category pills filter the grid in real time
- **Keyboard:** `/` focuses search · `Esc` clears search · `Space` stops playback
- Click the `+` on a tile to assign a one-key shortcut that plays it from anywhere

### Admin

Click **Admin**, log in, then:

- Record directly in browser (mic required — silence is auto-trimmed)
- Upload audio files (mp3, wav, ogg, webm, m4a)
- Assign names and categories (categories are free-text, autocompleted from existing ones)
- Edit a sound in place, bulk-select with checkboxes, or download a full backup zip

## Notes

- Audio files are stored locally in the `sounds/` folder
- No database needed for sounds — metadata is in `sounds_db.json`; user accounts live in `users.db` (SQLite)
- Search filters by name and category in real time
- **Browser-side state** — favorites, custom tile order, keybindings, pinned items, and volume are stored in `localStorage` per browser. They survive server redeploys but are not shared between devices/visitors. Clearing site data resets them.

---

## Deploy on Proxmox LXC

### 1. Create the LXC container

In the Proxmox web UI (or via shell):

```bash
# On the Proxmox host
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname soundboard \
  --memory 256 \
  --cores 1 \
  --rootfs local-lvm:4 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --start 1
```

> Adjust the template path, CT ID, memory, storage, and network to match your setup.

### 2. Enter the container and install dependencies

```bash
pct enter 200
```

```bash
apt update && apt install -y python3 python3-pip python3-venv git
```

### 3. Clone the repo

```bash
cd /opt
git clone https://github.com/apostle818/soundboard.git
cd soundboard
```

### 4. Set up a virtual environment and install packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Set the secret key and create your first admin user

```bash
cp .env.example .env
nano .env   # set SECRET_KEY to a long random string
```

`SECRET_KEY` is required — the app refuses to start without it. Generate one with
`openssl rand -hex 32`. Changing it invalidates every issued auth token.

Then create your first user:

```bash
source .venv/bin/activate
python manage.py adduser yourname
```

To manage users later:

```bash
python manage.py list
python manage.py passwd  yourname   # change password
python manage.py remove  yourname   # delete user
```

`.env` and `users.db` are gitignored — `git pull` will never overwrite them.

### 6. Run with gunicorn as a systemd service

Create the service file:

```bash
cat > /etc/systemd/system/soundboard.service << 'EOF'
[Unit]
Description=Soundboard
After=network.target

[Service]
User=root
WorkingDirectory=/opt/soundboard
ExecStart=/opt/soundboard/.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now soundboard
```

The app is now reachable at **http://\<container-ip\>:5000**.

### 7. (Optional) Put nginx in front

Install nginx inside the container:

```bash
apt install -y nginx
```

Create `/etc/nginx/sites-available/soundboard`:

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/soundboard /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default
systemctl restart nginx
```

The app is now reachable on port **80**. Add a Proxmox port-forward or a reverse proxy (e.g. Nginx Proxy Manager) on the host if you want it accessible from outside your LAN.

### 8. Update the app

```bash
cd /opt/soundboard && git pull && .venv/bin/pip install -r requirements.txt && systemctl restart soundboard
```

### 9. Persist data across container rebuilds (optional)

Bind-mount directories from the Proxmox host so audio files and users survive container deletion:

```bash
# On the Proxmox host — stop container first
pct stop 200
mkdir -p /mnt/soundboard-sounds /mnt/soundboard-data
pct set 200 -mp0 /mnt/soundboard-sounds,mp=/opt/soundboard/sounds
pct set 200 -mp1 /mnt/soundboard-data,mp=/opt/soundboard/data
pct start 200
```

Then symlink `users.db` and `sounds_db.json` into the data mount inside the container:

```bash
ln -sf /opt/soundboard/data/users.db      /opt/soundboard/users.db
ln -sf /opt/soundboard/data/sounds_db.json /opt/soundboard/sounds_db.json
```

> Fix ownership on the Proxmox host if needed: `chown 100000:100000 /mnt/soundboard-data`

---

## Deploy with Portainer (from GitHub)

An alternative to the LXC flow above: deploy as a Docker stack directly from this repository using Portainer. The repo ships a `Dockerfile` and `docker-compose.yml` so Portainer can build and run the app with no extra configuration.

> **HTTPS note.** Browser microphone recording (`getUserMedia`) requires HTTPS (or `localhost`). The stack itself only speaks plain HTTP on port 5000 — terminate TLS in your existing reverse proxy (Traefik, Nginx Proxy Manager, Caddy, …) pointing at `http://<docker-host>:5000`.

### 1. Add the stack in Portainer

1. **Stacks → Add stack → Repository.**
2. Fill in:
   - **Name:** `soundboard`
   - **Repository URL:** `https://github.com/apostle818/soundboard`
   - **Reference:** `refs/heads/main`
   - **Compose path:** `docker-compose.yml`
3. (Recommended) **Enable GitOps updates** so Portainer redeploys on every push (polling or webhook).
4. Under **Environment variables**, add:
   - `SECRET_KEY` — generate with `openssl rand -hex 32`
   - `SOUNDBOARD_PORT` — optional, defaults to `5000`
5. **Deploy the stack.**

### 2. Create the first admin user

Once the container is healthy:

```bash
docker exec -it soundboard python manage.py adduser yourname
```

Other user-management commands (`list`, `passwd`, `remove`) work the same way — just prefix them with `docker exec -it soundboard`.

### 3. Put it behind your reverse proxy

Point your existing TLS-terminating proxy at `http://<docker-host>:5000`. A minimal Traefik label set or NPM proxy host pointing at that upstream is enough; no special headers required beyond standard `Host` / `X-Forwarded-*` forwarding. Increase the upload size limit on the proxy (50 MB is a good starting point) to match the LXC nginx example above.

### 4. Updating

With GitOps updates enabled, push to `main` and Portainer redeploys automatically. Otherwise: **Stacks → soundboard → Pull and redeploy**.

### Persistent data

All state lives in the named volume `soundboard_data` (mounted at `/data` in the container):

- `/data/sounds/` — uploaded audio files
- `/data/sounds_db.json` — sound metadata
- `/data/users.db` — user accounts

The volume survives `docker compose down` and stack recreations. Back it up with any tool that can read a Docker volume (e.g. `docker run --rm -v soundboard_soundboard_data:/data -v $PWD:/backup alpine tar czf /backup/soundboard.tar.gz -C /data .`).

---

## Migrating from LXC to Portainer

The LXC and Portainer deployments are interchangeable — they share the same storage layout (`sounds/` + `sounds_db.json` + `users.db`). To migrate:

### 1. On the LXC: snapshot the state

```bash
systemctl stop soundboard
cd /opt/soundboard
tar czf /tmp/soundboard-state.tar.gz sounds sounds_db.json users.db
```

Also grab the existing `SECRET_KEY` from `/opt/soundboard/.env` — reuse it on the Portainer side so any active browser tokens stay valid.

### 2. Copy the tarball to the Portainer host

```bash
scp /tmp/soundboard-state.tar.gz user@portainer-host:/tmp/
```

### 3. Deploy the Portainer stack once (to create the volume), then stop it

Follow the Portainer steps above with the salvaged `SECRET_KEY`, deploy, then stop the stack from the Portainer UI. The `soundboard_data` volume now exists but is empty.

### 4. Seed the volume from the tarball

On the Portainer host:

```bash
docker run --rm \
  -v soundboard_soundboard_data:/data \
  -v /tmp/soundboard-state.tar.gz:/seed.tar.gz:ro \
  alpine sh -c "cd /data && tar xzf /seed.tar.gz && chown -R 1000:1000 ."
```

> The volume name is `<stack-name>_soundboard_data` — Portainer prefixes volume names with the stack name. Confirm with `docker volume ls | grep soundboard`.

### 5. Start the stack and verify

Start it from Portainer, then end-to-end test:

- Log in with an existing user → confirms `users.db` migrated.
- Existing sounds appear in the grid → confirms `sounds_db.json` migrated.
- A sound plays → confirms files under `sounds/` migrated.
- Upload a new sound, restart the container, confirm it persists.

### 6. Decommission the LXC

Only after the Portainer instance has been running successfully for long enough to be confident. Until then, keep the LXC stopped (not deleted) as a rollback.
