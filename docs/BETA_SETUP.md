# BAKLOG beta — setup for testers

Invite-only early access. **Free forever** to import your library. Everything runs on your machine.

---

## What you need

- **Windows 10 or 11** (primary beta target — packaged `.exe` when available)
- **macOS or Linux** — clone-and-run with Python 3.11+ (see below; no frozen installer yet)
- **Google Chrome or Chromium** (required for store Connect sign-in; set `BAKLOG_CHROME_PATH` if off the default path)
- **~200 MB disk space** for the app + your library data

You do **not** need a BAKLOG cloud account for local-only mode. If your invite includes Supabase login, use the email/password from your invite message.

---

## Download

**[Setup link — GitHub Release](https://github.com/Ogrods/BAKLOG/releases)**

> Until the packaged `.exe` ships, the release may be a zip that still requires Python 3.11+ — see the release notes for which asset to use. The goal is a single `BAKLOG.exe` with no Python install.

---

## Quick start (packaged `.exe` — target flow)

1. Download `BAKLOG-win64.zip` from the release page and unzip anywhere (e.g. `C:\BAKLOG\`).
2. Double-click **`BAKLOG.exe`** (or `Start BAKLOG.bat`).
3. Your browser should open to **http://127.0.0.1:8765** (open it manually if it does not).
4. Go to **Connections** → **Connect** for each store (start with **Steam**).
5. Click **Refresh** on the dashboard and watch your library count climb.

Your data (`games_*.json`, credentials, settings) stays in the same folder as the executable.

---

## Quick start (interim zip — Python still required)

If the release is a source folder zip:

1. Install **Python 3.11+** from [python.org](https://www.python.org/downloads/) (check "Add python to PATH").
2. Unzip the release and open a terminal in that folder.
3. Run: `pip install -r requirements.txt`
4. Run: `python server.py` or double-click **`Start BAKLOG.bat`**.
5. Open **http://127.0.0.1:8765** and follow steps 4–5 above.

---

## Quick start (macOS / Linux — clone and run)

Frozen installers are Windows-only for now. On macOS or Linux:

```bash
git clone https://github.com/Ogrods/BAKLOG.git
cd BAKLOG
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python server.py
```

Open **http://127.0.0.1:8765**, then **Connections** → **Connect** for each store.

**Store caveats on non-Windows:**

| Source | macOS / Linux |
|--------|----------------|
| Browser Connect (Steam, Epic, GOG web, etc.) | Supported |
| itch app (local `butler.db`) | Supported |
| GOG Galaxy (local) | macOS only — on Linux use **GOG (web)** |
| Amazon Games launcher | Windows only — use **Amazon (Prime Gaming, web)** Connect |

Unattended refresh: `./refresh.sh` (skips the Windows launcher Amazon path; run `python fetch_amazon.py --source web` after Prime web Connect if you use Amazon).

---

## Chrome / Edge

Connect drives a real browser window for sign-in (cookies, OAuth). BAKLOG does not bundle a browser. If Connect fails, install Chrome or Chromium and try again.

---

## Something broke?

Reply to your invite email or use **Copy bug bundle** in the app menu (⋮) and paste the result. It is scrubbed and stays local until you send it.

---

## Privacy reminder

- No telemetry. No central server holding your library.
- Store credentials are encrypted on your PC (OS keyring + local vault).
- See [PRIVACY.md](../PRIVACY.md) and [SECURITY.md](../SECURITY.md) for details.
