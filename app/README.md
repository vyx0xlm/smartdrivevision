# SmartDrive — Driver Drowsiness Family Portal

Web app for your FYP: **sign up / login**, **profile**, **emergency contacts**, **dashboard**, and **alert log**.

## Setup (local)

```bash
cd app
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — create an account, complete your profile, then add emergency contacts.

**Google sign-in:** enable Google in Firebase Console → Authentication, add `serviceAccountKey.json` and `firebase_web_config.json` in the `app` folder (see `.env`).

## Go live (backend + frontend)

See **[DEPLOY.md](../DEPLOY.md)** in the project root.

**Collaborators:** see **[COLLABORATORS.md](../COLLABORATORS.md)** to run your own live site without the repo owner’s PC.

Quick start:

```powershell
# Terminal 1 — backend + public HTTPS tunnel
powershell -ExecutionPolicy Bypass -File app\scripts\run-backend-live.ps1

# Edit smartdrivevision/public/config.js with your tunnel URL, then:
powershell -ExecutionPolicy Bypass -File app\scripts\deploy-frontend-live.ps1
```

- **Backend:** Flask + IoT API via Cloudflare tunnel URL  
- **Frontend:** Firebase Hosting (`smartdrive-vision.web.app`) → redirects to Flask

## Features

| Area | Purpose |
|------|---------|
| **Sign up / Login** | Email/password, or **Continue with Google**. |
| **Profile** | Account + driver details, profile photo, driver code for Pi. |
| **Emergency contacts** | Duplicate phone numbers blocked per driver. |
| **Dashboard** | Stats + recent alerts from IoT. |
| **Alert log** | Records when `POST /api/alert` is called after an alert. |

## API (IoT)

- `GET /api/driver/<driver_code>/emergency-phones` — phone list for GSM SMS.
- `POST /api/alert` — JSON `{"driver_code":"DR001"}` to log an alert.
- `GET /api/health` — health check.

## Database

SQLite: `smartdrive.db`.
