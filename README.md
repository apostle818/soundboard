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
pip install flask
```

### 2. Set your admin password

Open `app.py` and change this line near the top:

```python
ADMIN_PASSWORD = "changeme123"   # << CHANGE THIS
```

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

- **Visitors** — click any sound card to play
- **Admin** — click ⚙ Admin, enter your password, then:
  - Record directly in browser (mic required)
  - Upload audio files (mp3, wav, ogg, webm, m4a)
  - Assign names and categories
  - Delete sounds

## Notes

- Audio files are stored locally in the `sounds/` folder
- No database needed — metadata is stored in `sounds_db.json`
- Categories are free-text — just type them when adding a sound
- Search filters by name and category in real time

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

### 5. Set your admin password

```bash
nano app.py   # change ADMIN_PASSWORD = "changeme123" at the top
```

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

### 8. Persist audio across container rebuilds (optional)

Bind-mount a directory from the Proxmox host so audio files survive container deletion:

```bash
# On the Proxmox host — stop container first
pct stop 200
mkdir -p /mnt/soundboard-data
pct set 200 -mp0 /mnt/soundboard-data,mp=/opt/soundboard/sounds
pct start 200
```
