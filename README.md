# SmartDrive — Driver Drowsiness Family Portal

Web app for your FYP: **sign up / login**, **profile** (account only), **drivers**, **dedicated emergency contacts** (separate from profile), **dashboard**, and **alert log**.

## Setup

```bash
cd app
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — create an account, then register drivers and emergency contacts.

Set `SECRET_KEY` in production:

```bash
set SECRET_KEY=your-long-random-string
python app.py
```

## Features

| Area | Purpose |
|------|---------|
| **Sign up / Login** | Email/password or **Google sign-in** (Firebase). |
| **Forgot password** | Reset link via Firebase email. |
| **First-time guide** | Dashboard walkthrough for new users. |
| **Register driver** | Name, email, phone **pre-filled** from your profile. |
| **Emergency contacts** | **Duplicate phone numbers blocked** per driver. |
| **Profile** | Account settings (not emergency SMS list). |
| **Dashboard** | Stats + recent alerts from IoT. |
| **Alert log** | Records when `POST /api/alert` is called after an alert. |
| **Firebase (optional)** | Cloud Auth + Firestore so any device can use the site without your PC running. |

## Firebase setup (Google sign-in + live cloud)

1. Create a project at [Firebase Console](https://console.firebase.google.com/).
2. Enable **Authentication** → Email/Password and **Google**.
3. Create a **Firestore** database (production mode).
4. Project settings → Your apps → Web app → copy config to `firebase_web_config.json` (see `firebase_web_config.example.json`).
5. Project settings → Service accounts → **Generate new private key** → save as `serviceAccountKey.json` (never commit to git).
6. Copy `.env.example` to `.env` and set:

```bash
SECRET_KEY=your-secret
GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
FIREBASE_WEB_CONFIG_PATH=./firebase_web_config.json
USE_FIREBASE=1
```

7. In Firebase Console → Authentication → Settings → **Authorized domains**:
   - `localhost` (included by default)
   - `127.0.0.1` if you open `http://127.0.0.1:5000`
   - Your deploy host (e.g. `your-app.onrender.com`) — **not** raw LAN IPs like `172.20.10.2`

**`auth/unauthorized-domain` fix:** Google sign-in only works on **authorized** hostnames. Use `http://localhost:5000` on your laptop — **not** `http://172.20.x.x:5000`. Firebase does not allow random IP addresses. Email/password login still works on LAN IP; Google does not.

### Deploy so others can access (without your laptop)

Host the Flask app on a free cloud service, for example [Render](https://render.com):

- Build: `pip install -r requirements.txt`
- Start: `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`
- Upload env vars: `SECRET_KEY`, `GOOGLE_APPLICATION_CREDENTIALS` (paste JSON), `FIREBASE_WEB_CONFIG` (one-line JSON), `USE_FIREBASE=1`

Your Pi then uses the public URL: `http://YOUR-APP.onrender.com` instead of `http://172.20.x.x:5000`.

**Note:** Full Firestore migration for all routes is enabled with `USE_FIREBASE=1`. Without it, data stays in SQLite but Firebase Auth (Google / forgot password) still works when credentials are set.

## API (IoT)

- `GET /api/driver/<driver_id_or_device_id>/emergency-phones` — phone list for GSM SMS.
- `POST /api/alert` — JSON `{"device_id":"..."}` or `{"driver_id":1}` to log an alert (optional message).
- `GET /api/health` — health check.

## Offline GSM SMS on Raspberry Pi (no connection to Flask)

The **website is not required at alert time.** GSM SMS only needs your **modem + SIM card** with normal cellular coverage (typically 2G/3G/LTE SMS). Missing **WiFi to your PC/Flask** does **not** block SMS if contacts are stored **on the Pi** before the trip.

### Pattern: sync while online → use saved file offline

1. While the Pi has LAN/WiFi to the machine running SmartDrive (or Pi runs Flask on itself), periodically save numbers to a JSON file:

   ```bash
   python scripts/raspberry_fetch_contacts.py --url http://YOUR_SERVER_IP:5000 --id YOUR_DEVICE_ID --output ~/smartdrive/emergency_phones.json
   ```

   Use **`--id`** = the same **IoT Device ID** you set on the driver in the web app, or the numeric **driver id**.

2. Your drowsiness script, when firing the alert, should **first read** `emergency_phones.json` and SMS each listed number via the GSM AT interface. Only optionally call HTTP again if you want a fresh copy (not required offline).

3. Automate refresh with **cron** on the Pi (e.g. at home/office WiFi) so the latest contacts from family registration are mirrored locally before driving.

### How the Pi connects to your stack

| Piece | Typical connection |
|-------|---------------------|
| **Flask SmartDrive** | Pi reaches it over LAN (`http://192.168.x.x:5000`) or Flask runs **on the same Pi**. |
| **GSM modem** | USB serial or Pi UART TX/RX to SIM800/SIM7600 module; SMS via AT commands (**pyserial**) or PPP if you prefer. |
| **Camera / detection** | USB cam or CSI; your existing OpenCV/MediaPipe/Python job on Pi. |

**Important:** Persist `emergency_phones.json` **on the Pi’s SD card**, not “only” in RAM. The sync script replaces the file atomically after a successful download so GSM code always reads the last known good copy.

## Database

SQLite: `smartdrive.db`. Existing installs are migrated (adds `users`, `user_id` on drivers, `alert_events`).

**Note:** Drivers created before accounts existed have no `user_id` and will not appear — re-register under your account if needed.
