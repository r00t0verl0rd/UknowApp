# UknowApp

UknowApp is a school messaging MVP with a React admin panel, a FastAPI backend, SQLite storage and a Telegram bot.

## Local development on macOS

Create the environment file once:

```bash
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env` to enable the bot. Change `ADMIN_PASSWORD` before using the admin panel.

### Terminal 1 — backend and Telegram bot

```bash
cd ~/Desktop/UknowApp
python3 -m venv .venv   # only on first setup
source .venv/bin/activate
python -m pip install -r backend/requirements.txt   # first setup or after requirements change
python -m uvicorn app.main:app --app-dir backend --reload
```

### Terminal 2 — frontend

```bash
cd ~/Desktop/UknowApp/frontend
npm install             # first setup or after package changes
npm run dev
```

Open the admin panel at http://127.0.0.1:22222. The Vite development server proxies `/api` requests to the backend at http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/docs.

In Telegram, use `/start` or `/menu` to open the role-based interface. Students write directly to their assigned teacher in the bot chat. Teachers get a persistent Reply Keyboard with their active students, the latest incoming messages, and the number of messages awaiting a reply. Tap a student's **Написать** button to select that conversation, then send text or attachments normally. Use **К списку учеников** to switch recipients; when there are more than six active students, the keyboard includes page navigation.

The local SQLite database is created at `data/uknowapp.db`. Telegram attachments are archived under `data/media/` and shown in the admin conversation view (voice playback, video notes, photos, video and downloadable documents). Keep the `.env` file and the entire `data/` directory private; both are excluded from Git. The hosted Telegram Bot API currently allows downloads up to 20 MB; larger attachments are still forwarded by Telegram but cannot be archived locally by this version.

## VPS deployment with Docker Compose

The production setup uses:
- one FastAPI container which also runs the Telegram long-polling bot;
- one Caddy container serving the built React app and proxying API requests;
- a persistent Docker volume for SQLite and persistent volumes for Caddy's TLS certificates.

**Run only one backend instance and one Uvicorn worker.** The Telegram bot uses long polling; running multiple backend replicas with the same bot token would start competing polling processes.

### 1. Prepare the VPS

Install Docker Engine with the Docker Compose plugin. Point a DNS A record (and, if used, AAAA record) for your chosen subdomain to the VPS. Allow inbound TCP ports 80 and 443; allow UDP 443 for HTTP/3 if desired.

Clone the repository:

```bash
git clone https://github.com/r00t0verl0rd/UknowApp.git
cd UknowApp
cp .env.example .env
```

### 2. Configure secrets and domain

Edit `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your_botfather_token
ADMIN_USERNAME=admin
ADMIN_PASSWORD=paste-a-long-random-value-here
DATABASE_URL=
ALLOWED_ORIGINS=
DOMAIN=admin.example.com
SEED_DEMO_DATA=false
```

Generate a password with `openssl rand -hex 32` and paste it into `ADMIN_PASSWORD`. Replace `admin.example.com` with the real DNS name pointing to the VPS. Do not use the example domain. Keep `DATABASE_URL` empty in this file: Docker Compose supplies the SQLite path inside the persistent `app_data` volume. For the same-origin Caddy deployment, `ALLOWED_ORIGINS` can remain empty. Restrict the file:

```bash
chmod 600 .env
```

### 3. Build and start

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend frontend
```

When DNS is correct and ports 80/443 are reachable, Caddy automatically obtains and renews the HTTPS certificate. Open `https://admin.example.com`.

### 4. Update after a Git change

```bash
git pull origin main
docker compose up -d --build
docker compose logs -f backend frontend
```

### 5. Database backup

Create a consistent SQLite backup from the running container, then copy both the database and archived attachments to the VPS host:

```bash
docker compose exec backend python -c "import sqlite3; source=sqlite3.connect('/app/data/uknowapp.db'); target=sqlite3.connect('/tmp/uknowapp-backup.db'); source.backup(target); target.close(); source.close()"
docker compose cp backend:/tmp/uknowapp-backup.db ./uknowapp-backup.db
docker compose cp backend:/app/data/media ./media-backup
```

The database backup contains student and teacher data; the media backup contains private voice messages, videos, photos and documents. Store both securely and protect access to them. Restore the database to `data/uknowapp.db` and media files to `data/media/` together so message references remain valid. The `app_data`, `caddy_data` and `caddy_config` volumes must not be removed when updating the containers.

## Deployment notes

- The backend is not published directly to the internet; Caddy is the only public web service.
- Browser requests use the same domain in production, so the frontend does not need a hardcoded API host.
- SQLite is stored on a persistent volume. For a larger multi-instance deployment, move to PostgreSQL and redesign Telegram polling as a separately managed single worker before scaling the API.
- HTTP Basic authentication is retained for this MVP. Use HTTPS, a unique strong admin password, SSH key authentication and a VPS firewall. Before production use with real student data, add stronger account/session management, access auditing, rate limiting and a tested backup/restore process.
