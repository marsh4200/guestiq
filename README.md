# GuestIQ

Self-hosted **hotel guest check-in + in-room info** system. FastAPI + SQLite, Docker, port **9921**.

Two QR-driven guest flows plus a reception console:

1. **Arrival QR** → `/checkin` — guest fills in their details (name, contact, ID/passport, address, vehicle, pax). Saved for future stays. Reception then assigns a room + checkout date.
2. **Per-room QR** → `/room/{code}` — in-room page showing Wi-Fi SSID/password, restaurant name + phone, online menu link, reception & emergency contacts, checkout info.

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/marsh4200/guestiq/main/install.sh | bash
```

This clones/updates the repo into `~/guestiq`, builds the container on port 9921, and installs the update watcher (systemd if run as root, otherwise a background nohup process).

Then open `http://<host>:9921/admin` — default password is `admin` (change it under **Settings**).

## Manual run

```bash
git clone https://github.com/marsh4200/guestiq.git
cd guestiq
docker compose up -d --build
```

## Data & persistence

SQLite lives in `./data/guestiq.db`, bind-mounted into the container so it **survives rebuilds and updates**. Nothing important is stored inside the image.

## Updates

- The console **Updates** tab compares your installed `VERSION` against GitHub and shows the changelog from `versions/<ver>.md`.
- **Update now** drops a flag in `data/`; the host watcher (`update.sh --watch`) picks it up within ~30s, runs `git pull` + `docker compose up -d --build`.
- Manual: `cd ~/guestiq && ./update.sh`

Bump a release by editing `VERSION` and adding `versions/<new-version>.md`.

## Public URL / Cloudflare tunnel

QR codes encode links to your host. If you expose GuestIQ through a Cloudflare tunnel (or any domain), set **Settings → Public URL** (e.g. `https://guestiq.yourdomain.co.za`) so the QR codes point at the right address instead of the raw IP.

## Config (env, optional)

| Var | Default | Purpose |
|-----|---------|---------|
| `ADMIN_PASSWORD` | `admin` | initial admin password (first run only) |
| `GUESTIQ_REPO` | `marsh4200/guestiq` | repo used for update checks |
| `GUESTIQ_BRANCH` | `main` | branch used for update checks |

## Ports

`9921` (next in the 9913–9920 range already in use).
