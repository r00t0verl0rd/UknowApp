# UknowApp

UknowApp is a school messaging MVP with a React admin panel, a FastAPI backend, SQLite storage and a Telegram bot.

## Local development on macOS

Use a supported Python release (recommended: Python 3.11 or newer). Python 3.9 reached end of life on 2025-10-31 and no longer receives security updates. Existing Python 3.9 environments may still run with compatible dependency versions, but should be migrated to a supported interpreter.

Create the environment file once:

```bash
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env` to enable the bot. Change `ADMIN_PASSWORD` before using the admin panel.

### Terminal 1 — backend and Telegram bot

```bash
cd ~/Desktop/UknowApp
python3.11 -m venv .venv   # only on first setup; Python 3.11+ is required
source .venv/bin/activate
python -m pip install --upgrade pip
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

In Telegram, use `/start` or `/menu` to open the role-based interface. Students can continue writing directly to their assigned teacher in the bot's private chat.

### Student conversations inside Telegram group topics

UknowApp also supports a public-to-the-group conversation topic for each student:
1. Create a Telegram **supergroup** for the student and enable **Topics** in the group settings.
2. Create a topic named **🤖 Бот**.
3. Add the UknowApp bot to the group as an administrator (no additional administrative permissions are needed just for receiving group messages). Alternatively, disable the bot's Privacy Mode in @BotFather and remove/re-add the bot to the group so the new setting takes effect. Telegram's default Privacy Mode hides ordinary group messages from bots.
4. The student must first connect their Telegram account to UknowApp in the bot's private chat using the administrator-issued activation code.
5. No manual binding command is required. When the linked student sends their first message (text or attachment) in the intended **🤖 Бот** forum topic, UknowApp automatically binds that exact topic to the student's account and active teacher, provided the student has no other group binding and the topic is not already assigned to someone else.
6. The student can continue sending ordinary text, media, or files in that topic; a slash prefix is not required. The teacher receives messages in the usual UknowApp teacher panel; teacher replies are copied back into the same topic, where group members can see them.

Only messages sent by the linked student account in the bound topic are processed. Messages from classmates and other group members are ignored. The student's private bot chat remains available and works as before; replies are delivered to the same channel (private chat or group topic) where the student's latest unanswered message was sent. The optional `/bind_group` command remains available for manually moving the student's binding to another topic.

The bot does not post separate check-mark messages in the topic. Telegram controls its native message check marks. The Bot API cannot mark a student's group message as read when the teacher opens the separate private bot chat, so that action cannot turn the original group message's native check marks blue.

Teachers continue to get a persistent Reply Keyboard with their active students, the latest incoming messages, and the number of messages awaiting a reply. Tap a student's name to select that conversation, then send text or attachments normally. Use **К списку учеников** to switch recipients; when there are more than six active students, the keyboard includes page navigation.

Incoming non-text messages from students are also copied as native Telegram messages into the teacher's private bot chat, preceded by a short student-name label. Photos, videos, video notes, voice messages, audio, documents, animations, stickers and other copyable message types can be opened or played directly in Telegram. These attachment copies remain in the teacher's chat history after a reply; the conversation panel also shows the attachment type and its caption when present.

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

### 5. Full backup and server migration

Use **Дополнительно → Полная резервная копия UknowApp** in the administrator panel. The ZIP contains the complete `data/` directory, not only a hand-picked list of files:
- a consistent SQLite snapshot created through SQLite's online backup API (WAL-safe);
- all archived media and attachments;
- the Web Push private key;
- every other regular file stored under `data/`, including files added by future modules.

The versioned manifest records each file's size and SHA-256 checksum. Restore verifies the file list, checksums, archive paths and SQLite integrity before it schedules any replacement. Older `uknowapp-full-backup-v1` archives remain importable; because that old format never contained the Web Push key or other data files, the destination's existing non-media data files are retained when importing one.

The full restore is staged first and does not modify live data during upload. In Docker Compose, the backend then restarts automatically and applies the staged directory before database migrations and Telegram polling start. For a direct local Uvicorn launch, stop and start the backend process after the upload; the prepared restore is applied during its next startup. If startup is interrupted during the directory swap, the restore journal allows the next startup to roll back or resume safely.

For a move to another VPS:
1. Download the full ZIP from the old server.
2. Deploy the UknowApp code on the new server and configure its own `.env` (domain, admin credentials, Telegram token and other secrets).
3. Sign in to the new administrator panel and upload the ZIP in **Дополнительно**.
4. Let the Docker backend restart and apply the data. For a non-Docker deployment, restart Uvicorn manually.
5. Verify users, conversations, attachments, Web Push and Telegram before deleting the old server.

The ZIP intentionally does **not** contain `.env`, Telegram bot tokens, domain settings, TLS certificates or Caddy configuration. Those belong to the server deployment and must be configured separately. Keep the archive private: it contains personal data, message history, credentials hashes and the Web Push private key.

The separate **База данных отдельно** and **Медиафайлы отдельно** operations remain available for specialist recovery tasks. They are not a substitute for the full ZIP when moving servers. The `app_data`, `caddy_data` and `caddy_config` Docker volumes must not be removed during ordinary application updates.

**Important SQLite notes:**
- UknowApp uses SQLite write-ahead logging (WAL). Never copy only the raw live `.db` file or delete `-wal` / `-shm` files manually. The in-app full backup uses SQLite's online backup API.
- Message text and metadata are stored in SQLite; attachment bytes are stored separately in `data/media/`. The full archive packages both and checks that media references are accounted for.
- Deleting records makes their pages reusable, but does not necessarily shrink the database file immediately. Do not run `VACUUM` on every request or automatically at startup: it needs extra disk space and can block access while rebuilding the database. Compaction should be an explicit maintenance operation after a backup.

## Deployment notes

- The backend is not published directly to the internet; Caddy is the only public web service.
- Browser requests use the same domain in production, so the frontend does not need a hardcoded API host.
- SQLite is stored on a persistent volume. For a larger multi-instance deployment, move to PostgreSQL and redesign Telegram polling as a separately managed single worker before scaling the API.
- HTTP Basic authentication is retained for this MVP. Use HTTPS, a unique strong admin password, SSH key authentication and a VPS firewall. Before production use with real student data, add stronger account/session management, access auditing, rate limiting and a tested backup/restore process.


## Web panel roles and messaging

The same browser panel supports two roles:

- **Administrator** signs in with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`. The administrator keeps access to the school graph, users, assignments and every active conversation. In any conversation the administrator can post a message as **Администратор**; it is saved to the shared history and delivered to the student and teacher through Telegram.
- **Teacher** signs in with their web-panel login and one shared access code. The same code also connects the teacher's Telegram account to the bot. A teacher sees a read-only graph containing only their own profile and their assigned active students, plus their own active student conversations. Teachers can reply from the browser but cannot edit the graph, assignments or user directory.

To enable access for a teacher, open **Пользователи** in the administrator panel and create the teacher profile. The login defaults to the teacher's full name and can be changed. On save, UknowApp automatically generates one access code in the `XXXX-XXXX` format and shows it to the administrator for manual delivery. For the web panel, the teacher enters their login and this code; for Telegram, the teacher sends only this code to the bot. The code remains valid until it is replaced. The database stores a salted PBKDF2 hash for web authentication and a SHA-256 lookup hash for Telegram; the plain code is not stored. Use **Новый код** in the teacher's user row or **Сгенерировать новый код** in the profile to replace it. The previous code immediately stops working for both web login and Telegram reconnection, and active teacher web sessions are revoked.

- **Student** continues to use a separate one-time Telegram activation code. It expires after 15 minutes and does not provide web-panel access.

The browser chat supports text and file uploads (up to 20 MB) and displays archived media, audio, video and documents in the same conversation. Teachers can filter message history by all messages, attachments, audio, photos or files. The panel uses one shared Server-Sent Events (SSE) connection for live conversation updates across all sections. It updates inbox counters in the background and synchronizes full message history only for the currently selected conversation; reconnects replay missed events where supported. Teacher replies are delivered to the student's Telegram; if the student's latest unanswered message came from their linked forum topic, the reply is sent to that topic. Administrator messages are added to that same conversation and delivered to both participants. In the teacher's Telegram inbox, copied student files now carry the student's name in the media caption whenever Telegram supports captions; non-captionable message types receive a separate identity label.
