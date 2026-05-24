# Collaborator guide — run SmartDrive live (without the repo owner’s PC)

Each collaborator runs **their own** Flask backend. You do **not** need the project owner’s computer to stay on.

SmartDrive has two parts:

| Part | What it is |
|------|------------|
| **Backend** | Flask app (web pages + IoT API) — **you host this** |
| **Frontend entry** | Firebase Hosting — optional redirect to your Flask `/login` |

The simplest way to go live: run Flask + a Cloudflare tunnel, then open your public `https://….trycloudflare.com/login` URL.

---

## 1. Clone the repo

```powershell
git clone https://github.com/YOUR-ORG/YOUR-REPO.git
cd YOUR-REPO
```

Replace the URL with your team’s actual GitHub repo.

---

## 2. Install prerequisites

### Python

- Python **3.10+**
- Install dependencies:

```powershell
cd app
python -m pip install -r requirements.txt
```

### Cloudflare Tunnel (free public HTTPS URL)

```powershell
winget install Cloudflare.cloudflared
```

### Firebase CLI (only if you will deploy Hosting)

```powershell
npm install -g firebase-tools
firebase login
```

---

## 3. Add local secret files (not on GitHub)

Copy the env template:

```powershell
cd app
copy .env.example .env
```

Edit `.env` and set a random `SECRET_KEY`.

You also need these files in the `app/` folder:

| File | How to get it |
|------|----------------|
| `serviceAccountKey.json` | Ask the repo owner to share securely **or** Firebase Console → Project settings → Service accounts → Generate new private key |
| `firebase_web_config.json` | Usually already in the repo; otherwise Firebase Console → Project settings → Your apps → Web config |

**Never commit** `.env` or `serviceAccountKey.json` to GitHub.

---

## 4. Run your own live backend

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File app\scripts\run-backend-live.ps1
```

This starts:

- Flask on `http://127.0.0.1:5000`
- A public HTTPS URL like `https://random-words.trycloudflare.com`

**Copy that URL** from the terminal output.

Test in a browser:

```
https://YOUR-TUNNEL-URL.trycloudflare.com/login
```

Keep this terminal **open** while demoing. Closing it stops your live site.

---

## 5. Use the app

1. Open your tunnel URL `/login`
2. Sign up or sign in (email or Google)
3. Complete **Profile** (name, phone, vehicle, profile photo)
4. Add **Emergency contacts**
5. Use your **driver code** from Profile for the Raspberry Pi API

---

## 6. Frontend options

### Option A — Tunnel URL only (easiest)

Share this link with your team or examiner:

```
https://YOUR-TUNNEL-URL.trycloudflare.com/login
```

No Firebase deploy required.

### Option B — Firebase Hosting redirect

1. Edit `smartdrivevision/public/config.js`:

```javascript
window.SMARTDRIVE_API = 'https://YOUR-TUNNEL-URL.trycloudflare.com';
```

2. Deploy (you need access to the Firebase project):

```powershell
powershell -ExecutionPolicy Bypass -File app\scripts\deploy-frontend-live.ps1
```

Public link: `https://smartdrive-vision.web.app` → redirects to your Flask login.

> **Note:** Whoever deploys Hosting last sets the URL everyone sees on the Firebase domain.

---

## 7. Google sign-in on your live URL

Firebase Console → **Authentication** → **Settings** → **Authorized domains**

Add:

- `smartdrive-vision.web.app` (if using Firebase Hosting)
- `smartdrive-vision.firebaseapp.com`
- Your tunnel domain, e.g. `xxxx.trycloudflare.com`

Ask the project owner to add your tunnel domain if you cannot access Firebase Console.

---

## 8. Raspberry Pi / IoT API

Use **your** tunnel URL and **your** driver code from Profile (e.g. `DR001`):

```
GET  https://YOUR-TUNNEL-URL.trycloudflare.com/api/driver/DR001/emergency-phones
POST https://YOUR-TUNNEL-URL.trycloudflare.com/api/alert
GET  https://YOUR-TUNNEL-URL.trycloudflare.com/api/health
```

Example alert body:

```json
{ "driver_code": "DR001", "alert_type": "SMS" }
```

---

## 9. What the repo owner should provide

| Item | Why |
|------|-----|
| GitHub repo access | Clone the code |
| `serviceAccountKey.json` (secure share) or Firebase project member access | Google sign-in backend |
| Firebase **Editor** role (optional) | Deploy Hosting |
| Add your `trycloudflare.com` or `username.pythonanywhere.com` domain | Google OAuth on your live URL |

---

## 10. PythonAnywhere (recommended for the whole team)

**Best option if you want one shared live site** without anyone’s PC running:

| Who | What to do |
|-----|------------|
| **One team member** | Deploy to [PythonAnywhere](https://www.pythonanywhere.com) — see [DEPLOY.md](DEPLOY.md#pythonanywhere-recommended-for-fyp--always-on-free-tier) |
| **Everyone else** | Use `https://USERNAME.pythonanywhere.com/login` — no tunnel, no local Flask |

Benefits:
- Stable URL (does not change on restart)
- Site stays online when laptops are off
- **One database** — shared accounts and emergency contacts for the whole team

Each collaborator can also create their **own** PythonAnywhere account for a separate demo instance.

---

## 11. Important notes

### Separate databases

Each collaborator gets their own local `smartdrive.db`. Accounts and emergency contacts are **not** shared unless the team uses **one** shared cloud server.

### Tunnel URL changes

Quick tunnels get a **new URL** every time you restart `run-backend-live.ps1`. After restart:

1. Update `smartdrivevision/public/config.js` (if using Firebase)
2. Redeploy Hosting (if needed)
3. Add the new domain in Firebase Authorized domains (for Google sign-in)

### Stable URL (optional)

For a URL that does not change, set up a [named Cloudflare tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/) with a free Cloudflare account.

### Always-on without your PC

See **PythonAnywhere** (section 10 above) or Docker cloud deploy in [DEPLOY.md](DEPLOY.md).

## Quick checklist

- [ ] Cloned repo
- [ ] `pip install -r requirements.txt`
- [ ] Created `.env` + added `serviceAccountKey.json`
- [ ] Ran `run-backend-live.ps1`
- [ ] `/login` works on tunnel URL
- [ ] Profile + emergency contacts set up
- [ ] (Optional) Updated `config.js` and deployed Firebase Hosting
- [ ] (Optional) Tunnel domain added for Google sign-in

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Google sign-in fails | Add your live domain to Firebase Authorized domains (`trycloudflare.com` or `pythonanywhere.com`) |
| `530` / tunnel not loading | Try another network; campus Wi‑Fi may block tunnels |
| `serviceAccountKey.json` missing | Get it from repo owner or Firebase Console |
| Firebase deploy denied | Ask owner to add your Google account in Firebase project |
| Pi cannot reach API | Use **your** current tunnel URL, not someone else’s |

More detail: [DEPLOY.md](DEPLOY.md)
