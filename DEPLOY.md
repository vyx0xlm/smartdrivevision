# Live deployment guide — backend + frontend (free)

> **Collaborators:** if you cloned this repo and need to host without the owner’s PC, read **[COLLABORATORS.md](COLLABORATORS.md)** first.

SmartDrive has two parts when going live:

| Part | What it is | Where it runs |
|------|------------|---------------|
| **Backend** | Flask app (pages + IoT API) | Your PC + Cloudflare Tunnel (free HTTPS) |
| **Frontend entry** | Firebase Hosting | Redirects visitors to your live Flask `/login` |

The Flask app serves **both** the web UI and the API (`/api/driver/...`, `/api/alert`). Firebase Hosting is the public link you share; it forwards users to Flask.

---

## Prerequisites

1. **Python 3.10+** with dependencies:
   ```powershell
   cd app
   python -m pip install -r requirements.txt
   ```

2. **Cloudflare Tunnel CLI** (free public URL for Flask):
   ```powershell
   winget install Cloudflare.cloudflared
   ```

3. **Firebase CLI** (already installed if `firebase --version` works):
   ```powershell
   npm install -g firebase-tools
   firebase login
   ```

4. **Google sign-in on live site** — Firebase Console → Authentication → Settings → **Authorized domains**, add:
   - `smartdrive-vision.web.app`
   - `smartdrive-vision.firebaseapp.com`
   - Your tunnel domain, e.g. `xxxx.trycloudflare.com` (add after first tunnel run)

---

## Step 1 — Start the backend live

Open **Terminal 1**:

```powershell
powershell -ExecutionPolicy Bypass -File app\scripts\run-backend-live.ps1
```

This starts:
- Flask on `http://127.0.0.1:5000` (Waitress)
- Cloudflare tunnel with a public URL like `https://random-words.trycloudflare.com`

**Copy the `https://….trycloudflare.com` URL** from the tunnel output.

Test it in a browser: `https://YOUR-TUNNEL-URL/login`

> Keep this terminal open. Closing it stops the live backend.

---

## Step 2 — Connect Firebase frontend

Edit `smartdrivevision/public/config.js`:

```javascript
window.SMARTDRIVE_API = 'https://YOUR-TUNNEL-URL.trycloudflare.com';
```

Deploy hosting:

```powershell
powershell -ExecutionPolicy Bypass -File app\scripts\deploy-frontend-live.ps1
```

Or manually:

```powershell
cd smartdrivevision
firebase deploy --only hosting
```

**Live frontend:** https://smartdrive-vision.web.app → redirects to your Flask login.

---

## Step 3 — Raspberry Pi API

Use your **driver code** from Profile (e.g. `DR001`):

```
GET https://YOUR-TUNNEL-URL.trycloudflare.com/api/driver/DR001/emergency-phones
POST https://YOUR-TUNNEL-URL.trycloudflare.com/api/alert
```

Health check: `GET …/api/health`

---

## Important notes

### Tunnel URL changes
Quick tunnels (`trycloudflare.com`) get a **new URL each time** you restart. After restarting:
1. Update `smartdrivevision/public/config.js`
2. Run `firebase deploy --only hosting` again
3. Add the new tunnel domain in Firebase Authorized domains

For a **stable URL**, create a free [named Cloudflare tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/) with your Cloudflare account.

### PC must stay on
The free tunnel exposes your **local** Flask app. Your computer must run the backend script while you demo or use the Pi API.

### Always-on cloud backend (optional)
To run without your PC, deploy the Docker image to **Google Cloud Run**, **Railway**, or **Fly.io**, then set `SMARTDRIVE_API` in `config.js` to that URL. See `app/Dockerfile`.

```bash
cd app
docker build -t smartdrive .
docker run -p 8080:8080 -e SECRET_KEY=your-secret smartdrive
```

---

## PythonAnywhere (recommended for FYP — always on, free tier)

[PythonAnywhere](https://www.pythonanywhere.com) hosts Flask 24/7 without your PC or a tunnel. Your URL is stable:

`https://YOUR_USERNAME.pythonanywhere.com`

| vs Cloudflare tunnel | PythonAnywhere |
|----------------------|----------------|
| PC must stay on | No — runs in the cloud |
| URL changes each restart | Stable URL |
| Good for quick tests | Good for demos + collaborators + Pi |

### 1. Create account & upload code

1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free tier is enough to start).
2. Use the default **`mysite`** folder: `/home/YOUR_USERNAME/mysite`
3. Upload the **contents of the `app/` folder** into `mysite` (not the whole repo):

```
/home/alyaa/mysite/
  app.py
  data_store.py
  firebase_service.py
  requirements.txt
  templates/
  static/
  .env
  serviceAccountKey.json
  firebase_web_config.json
```

### 2. Virtualenv & packages

Open a **Bash** console on PythonAnywhere:

```bash
cd ~/mysite
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

(`waitress` / `gunicorn` are not needed — PythonAnywhere runs WSGI for you.)

### 3. Secret files

In `/home/YOUR_USERNAME/mysite/` upload or create:

- `.env` (from `.env.example`, set `SECRET_KEY`)
- `serviceAccountKey.json`
- `firebase_web_config.json`

Do **not** set `BEHIND_PROXY` on PythonAnywhere.

### 4. WSGI configuration

**Web** tab → click the **WSGI configuration file** link and **replace all contents** with:

```python
import os
import sys

PROJECT_DIR = '/home/alyaa/mysite'  # change alyaa if different username

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.chdir(PROJECT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, '.env'))

from app import app as application, init_db

init_db()
```

Use `from app import app` — **not** `from flask_app import app` (the default PA template is wrong for this project).

**Web** tab settings:

| Setting | Value |
|---------|--------|
| Source code | `/home/YOUR_USERNAME/mysite` |
| Working directory | `/home/YOUR_USERNAME/mysite` |
| Virtualenv | `/home/YOUR_USERNAME/mysite/venv` |

**Static files** mapping (Web tab):

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/YOUR_USERNAME/mysite/static/` |

Click **Reload** on the Web tab.

Test: `https://YOUR_USERNAME.pythonanywhere.com/login`

### 5. Firebase & frontend

**Google sign-in** — Firebase Console → Authentication → Authorized domains → add:

`YOUR_USERNAME.pythonanywhere.com`

**Firebase Hosting** (optional) — `smartdrivevision/public/config.js`:

```javascript
window.SMARTDRIVE_API = 'https://YOUR_USERNAME.pythonanywhere.com';
```

Then `firebase deploy --only hosting`.

Or use the PythonAnywhere URL directly — no Firebase deploy needed.

### 6. Pi API

```
GET  https://YOUR_USERNAME.pythonanywhere.com/api/driver/DR001/emergency-phones
POST https://YOUR_USERNAME.pythonanywhere.com/api/alert
GET  https://YOUR_USERNAME.pythonanywhere.com/api/health
```

### Free tier limits (know before demo)

- One web app, `*.pythonanywhere.com` domain only
- Limited CPU — fine for FYP traffic
- SQLite + profile uploads work if files stay in your home folder
- If Google sign-in fails, check Authorized domains and that `serviceAccountKey.json` is uploaded

### Troubleshooting “Something went wrong” / Unhandled Exception

1. **Web tab → Log files → Error log** (or `alyaa.error.log`) — scroll to the **bottom** for the real error.
2. **Fix WSGI file** — replace default `from flask_app import app` with `from app import app` and set `PROJECT_DIR = '/home/alyaa/mysite'`.
3. **Virtualenv** — Web tab must point to `/home/alyaa/mysite/venv` where you ran `pip install -r requirements.txt`.
4. **Run diagnostics** in a Bash console:
   ```bash
   cd ~/mysite
   source venv/bin/activate
   python check_deploy.py
   ```
5. **Common errors:**

| Error in log | Fix |
|--------------|-----|
| `No module named 'flask_app'` | Replace WSGI with `from app import app` — see section 4 above |
| `No module named 'flask_cors'` | `pip install -r requirements.txt` in your virtualenv |
| `PROJECT_DIR does not exist` | Use `/home/YOUR_USERNAME/mysite` |
| `ImportError: cannot import name 'app'` | `app.py` must be directly inside `mysite/` |
| `Permission denied` on database | Keep project inside `/home/alyaa/` (not `/tmp`) |
| Template not found | Source code / working directory must be the `app/` folder |

6. After any fix → **Web tab → Reload** green button.

---

## Render (always-on cloud — e.g. drive-vision.onrender.com)

### Render dashboard settings

| Setting | Value |
|---------|--------|
| **Root directory** | `app` |
| **Build command** | `pip install -r requirements.txt` |
| **Start command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120` |

Use **`--workers 1`** — SQLite breaks with multiple Gunicorn workers.

### Environment variables (Render → Environment)

| Key | Value |
|-----|--------|
| `SECRET_KEY` | Long random string (required — keeps sessions working) |
| `FLASK_DEBUG` | `0` |
| `FIREBASE_WEB_CONFIG` | Paste entire contents of `firebase_web_config.json` as one line |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Paste entire contents of `serviceAccountKey.json` as one line |
| `APP_URL` | `https://drive-vision.onrender.com` (your public URL — used in reset emails) |

These JSON files are **not on GitHub** — you must add them as env vars on Render for Google sign-in to appear.

### Password reset email (Gmail SMTP)

Forgot-password sends a reset link by email. On Render, add:

| Key | Example value |
|-----|----------------|
| `MAIL_SERVER` | `smtp.gmail.com` |
| `MAIL_PORT` | `587` |
| `MAIL_USE_TLS` | `1` |
| `MAIL_USERNAME` | Your Gmail address |
| `MAIL_PASSWORD` | Gmail **App Password** (not your normal password) |
| `MAIL_DEFAULT_SENDER` | `SmartDrive <your@gmail.com>` |

**Create a Gmail App Password:**

1. Google Account → **Security** → turn on **2-Step Verification** (required).
2. Security → **App passwords** → create one for “Mail” / “Other (SmartDrive)”.
3. Copy the 16-character password into Render as `MAIL_PASSWORD`.

Redeploy after saving env vars. Test at `/forgot-password` on your live site.

> Google-only accounts (signed up with “Continue with Google”) have no local password — they cannot use email reset; use Google sign-in instead.

### Firebase authorized domain

Firebase Console → Authentication → Settings → **Authorized domains** → add:

`drive-vision.onrender.com` (your Render subdomain)

### Fix “Internal Server Error” after sign-in

Usually caused by:
1. Database not initialized → fixed in latest code (`init_db()` on startup)
2. Multiple Gunicorn workers + SQLite → use `--workers 1`
3. Missing `SECRET_KEY` → set in Render env vars

After updating code on GitHub, trigger **Manual Deploy** on Render. Check **Logs** tab for the exact error.

### Google button missing

The **Continue with Google** button only shows when `FIREBASE_WEB_CONFIG` is set (file or env var). On Render, add both Firebase env vars above and redeploy.

### Pi API

```
https://YOUR-SERVICE.onrender.com/api/driver/DR001/emergency-phones
https://YOUR-SERVICE.onrender.com/api/alert
https://YOUR-SERVICE.onrender.com/api/health
```

**Note:** Render free tier sleeps after inactivity — first request may take ~30 seconds to wake up.

---

## Quick checklist

- [ ] Backend script running → tunnel URL works at `/login`
- [ ] `config.js` updated with tunnel URL
- [ ] Firebase hosting deployed
- [ ] Authorized domains added for Google sign-in
- [ ] Profile filled in + emergency contacts added
- [ ] Pi tested against live `/api/health`
