# Deploying ClubDJ on Render (free)

Render is a cloud platform with a **free tier** for web services. The ClubDJ bot is deployed there as a *web service* (because Render's free tier only offers web services, not pure background workers).

> **Yes, you can host it on Render.** One honest caveat: Render's free plan **suspends a web service after ~15 minutes of no HTTP traffic**. A DJ bot normally has no HTTP traffic — so on the free plan the service will sleep, and the bot will disconnect from the Clubhouse room until the service wakes up. Section 3 shows how to keep it awake for free.

## What you get on Render

| Plan | Cost | Behaviour |
|---|---|---|
| Free | $0 | 750 instance-hours/month; sleeps after ~15 min idle; slow cold-start wake |
| Starter | $7/month | Always on, never sleeps — best for a 24/7 DJ bot |

## Step 1 — Deploy from GitHub

1. Push your repo to GitHub (already done — it is at `github.com/vincenzo-afk/clubhouse-dj`).
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New +** → **Blueprint**.
3. Connect your GitHub account and select `vincenzo-afk/clubhouse-dj`.
4. Render reads `render.yaml` automatically and creates the **clubdj-bot** service with the correct build/start commands and `PORT=10000`.
5. Alternatively (manual): **New + → Web Service**, connect the repo, set:
   - Build Command: `pip install -r requirements.txt && mkdir -p playlist/cache playlist/tts_cache logs`
   - Start Command: `python3 main.py`
   - Environment variable: `PORT = 10000`

## Step 2 — Configure the bot (Render environment variables)

Render instances are stateless and ephemeral — do **not** rely on files on disk. Set everything through environment variables instead. Add these in the service's **Environment** tab:

| Key | Value |
|---|---|
| `PHONE_NUMBER` | Your Clubhouse-registered phone number |
| `ROOM_ID` | The Clubhouse room/channel ID to join |
| `USER_ID` | From `auth_token.json` (see Step 3) |
| `USER_TOKEN` | From `auth_token.json` |
| `DEVICE_ID` | From `auth_token.json` (empty string if absent) |
| `PORT` | `10000` |
| `RENDER` | `1` |

Then edit `main.py`'s `load_auth()` to read from these env vars when present (the current code loads `auth_token.json` from disk, which Render discards on every restart — a small follow-up change, see the note at the end).

## Step 3 — Get your Clubhouse token once

Run `python3 auth_setup.py` **locally** (or on any machine) to complete phone + OTP login. The script writes `auth_token.json`. Copy the three values (`user_id`, `user_token`, `device_id`) into the Render environment variables above. Render keeps env vars securely — they do not need to be stored on disk.

## Step 4 — Keep the free service awake

Because the free plan sleeps the service after ~15 minutes idle, the bot will drop from the Clubhouse room during sleep. Two free options:

1. **Free ping cron job** (recommended): create a free cron job on [cron-job.org](https://cron-job.org) or [uptimerobot.com](https://uptimerobot.com) that hits `https://<your-service>.onrender.com/` every 10 minutes. The bot's built-in health endpoint (`GET /`) answers instantly and keeps the service alive.
2. **Render cron**: Render's free tier includes limited cron jobs — create one that hits the service URL periodically.

This keeps the service alive without paying. The $7 Starter plan removes the need entirely (always on).

## Step 5 — Verify

1. Wait for the build to finish (Render logs show `Health endpoint listening on :10000`).
2. Open `https://<your-service>.onrender.com/` — you should see `{"status":"OK","service":"ClubDJ","playing":...}`.
3. Join the configured Clubhouse room — the bot should appear and respond to `!play`, `!queue`, `!help`, etc.

## Important note — Clubhouse API + Render

Clubhouse's private API is not officially supported for bots. The connection (login, join room, Agora audio, PubNub chat) works via `clubhouse-py`, but tokens can be invalidated when you change your password or Clubhouse rotates sessions. If the bot stops joining rooms, re-run `auth_setup.py` locally and update the `USER_TOKEN` env var on Render.

## Follow-up improvement (env-based auth — recommended)

Currently `load_auth()` reads `./auth_token.json`. Since Render has no persistent disk, the recommended change is:

```python
def load_auth(config: dict):
    # Render / env-first: prefer environment variables
    uid = os.environ.get("USER_ID")
    token = os.environ.get("USER_TOKEN")
    device = os.environ.get("DEVICE_ID", "")
    if uid and token:
        return {"user_id": uid, "user_token": token, "device_id": device}
    # fallback to local file (local dev)
    ...
```

This makes Render deployments completely zero-touch after initial setup.
