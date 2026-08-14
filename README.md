# ClubDJ Bot for Clubhouse

An automated music DJ bot for Clubhouse rooms. It joins a room, accepts song requests through chat commands, streams music continuously, makes text-to-speech announcements, and runs an Auto DJ that keeps the room alive when the queue is empty.

**Features**

| Feature | Description |
|---|---|
| Chat commands | `!play`, `!skip`, `!queue`, `!np`, `!timer`, `!stop`, `!start`, `!clear`, `!help` |
| Song queue | FIFO queue (configurable capacity), plays immediately when nothing is playing |
| Skip voting | Audience votes to skip (default: 3 votes); moderators skip instantly |
| Auto DJ | Keeps music going: picks random tracks from the default playlist when the queue is empty or the room goes silent |
| TTS announcements | Announces each song ("Now playing…") and queue events in a robot voice |
| Silence detection | RMS-based audio monitor + wall-clock timer; silence threshold is adjustable in-chat (`!timer 15`) |
| Audio pipeline | yt-dlp downloads audio → ffmpeg converts to 16 kHz mono PCM → streamed to the Clubhouse Agora channel |
| Keepalive | Active ping loop + automatic reconnect with watchdog |
| Demo mode | Fully local operation (no Clubhouse account needed) for testing |

---

## Quick start

```bash
# 1. Install everything (system packages + Python venv + systemd auto-start)
chmod +x install.sh start.sh
./install.sh

# 2. Configure
nano config.json            # set phone_number and room_id

# 3. Authenticate (one time)
python3 auth_setup.py       # stores the token in auth_token.json

# 4. Start the bot
sudo systemctl start clubdj      # auto-starts on boot
# or, without systemd (macOS / manual):
./start.sh
./start.sh --daemon              # background with log + watchdog
```

To try it **without a Clubhouse account** first:

```bash
python3 main.py --demo
```

---

## Authentication

ClubDJ logs into Clubhouse using a token from a real Clubhouse account. This is done once and saved to `auth_token.json`.

1. Set your phone number in `config.json` (`phone_number`).
2. Run `python3 auth_setup.py` and follow the instructions (OTP verification).
3. The script saves `{ "user_id", "user_token", "device_id" }` to `auth_token.json` automatically.

**Important:** the bot will appear in rooms under *your* Clubhouse account. If your account session is invalidated (password change, logout), re-run `auth_setup.py`.

---

## Configuration (`config.json`)

| Key | Default | Meaning |
|---|---|---|
| `phone_number` | — | Your Clubhouse-registered phone number |
| `room_id` | — | The Clubhouse channel/room ID to join |
| `silence_threshold_minutes` | `10` | Minutes of silence before Auto DJ kicks in |
| `auto_dj_mode` | `true` | Enable the Auto DJ fallback |
| `default_genre` | `"lofi tamil chill"` | Search genre for Auto DJ picks |
| `max_song_duration_seconds` | `600` | Skip tracks longer than this |
| `max_queue_size` | `20` | Maximum pending songs |
| `announce_songs` | `true` | TTS announcement before each song |
| `skip_votes_required` | `3` | Votes needed for a skip |
| `bot_name` | `"ClubDJ"` | Display name |
| `agora_app_id` / `agora_token` / `agora_uid` | — | Only needed for direct audio injection without the room handshake |
| `reconnect_delay_seconds` / `max_reconnect_attempts` / `watchdog_check_interval` | 5 / 10 / 30 | Reconnection behaviour |

Songs the Auto DJ picks from are defined in `playlist/default_songs.txt` (one search query per line).

---

## Chat commands

| Command | Who | Effect |
|---|---|---|
| `!play <song or URL>` | everyone | Add to queue; starts immediately if idle |
| `!skip` | everyone | Vote to skip (3 votes); mods skip instantly |
| `!queue` | everyone | List pending songs |
| `!np` | everyone | Announce the current song |
| `!timer <5–60>` | moderators | Change silence threshold (minutes) |
| `!stop` / `!start` | moderators | Disable / enable Auto DJ |
| `!clear` | everyone | Clear the pending queue |
| `!help` | everyone | Show command list |

---

## Hosting — free, on your own machine

The bot is a long-running process, so it needs a machine that stays on. Free options:

### On a Linux server or Raspberry Pi (systemd — auto-start on boot, auto-restart on crash)

```bash
./install.sh            # creates the `clubdj` systemd service
sudo systemctl start clubdj
sudo systemctl enable clubdj   # auto-start on boot
journalctl -u clubdj -f        # follow the logs
```

The systemd service restarts the bot automatically on crash (`Restart=always`) and starts it at boot.

### On macOS or any machine without systemd

```bash
./start.sh --daemon     # background process with log file
./start.sh --status     # check status
./start.sh --logs       # tail logs
```

For persistence across logins, run it inside `tmux`/`screen`, or add it to your platform's startup items.

### On Windows

```powershell
pip install -r requirements.txt
python main.py
```

Run it inside a scheduled task (set "Run whether user is logged on or not") or simply leave it running.

### On Render (free cloud hosting)

The bot deploys to [Render](https://render.com) as a web service — one click from GitHub. The repo ships a `render.yaml` Blueprint plus a health endpoint (`GET /`) so Render can route traffic and free cron pings can keep the service awake. Full step-by-step instructions: [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md). Note that Render's **free plan sleeps the service after ~15 min of idle HTTP traffic**, so a free ping cron (cron-job.org / uptimerobot) is recommended — or the $7/mo Starter plan for always-on.

### Note on YouTube downloads

Some networks trigger YouTube's bot detection ("Sign in to confirm you're not a bot") and downloads fail. Two easy fixes:

1. Export cookies from your browser (e.g., the *Get cookies.txt LOCALLY* extension) and save them as `cookies.txt` next to `main.py` — yt-dlp picks it up automatically, **or**
2. Use direct audio URLs with `!play <URL>` (e.g., from archive.org), which never hit the block.

---

## Testing

```bash
python3 -m unittest discover tests     # 29 unit tests (no Clubhouse account needed)
python3 main.py --demo                 # full pipeline locally
```

The demo mode exercises the whole pipeline: chat parsing → queue → download → convert → stream → TTS → skip voting → silence timer → Auto DJ.

---

## Project structure

```
main.py                      # entry point; wires everything together
auth_setup.py                # one-time Clubhouse authentication helper
config.json                  # all settings
bot/
  clubhouse_client.py        # Clubhouse API (login, join room, PubNub chat)
  audio_player.py            # yt-dlp → ffmpeg → Agora/local PCM streaming
  queue_manager.py           # song queue + Auto DJ fallback
  announcer.py               # gTTS / pyttsx3 announcements
  command_handler.py         # chat command parsing and dispatch
  scheduler.py               # APScheduler silence countdown
  silence_detector.py        # RMS-based silence detection
playlist/default_songs.txt   # Auto DJ song list
systemd/clubdj.service       # systemd unit (auto-start on boot)
install.sh / start.sh        # setup + management scripts
tests/                       # unit + end-to-end tests
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not obtain audio for …" | Run `./install.sh` (yt-dlp/ffmpeg missing); or YouTube bot-block → use `cookies.txt` / direct URLs |
| "Clubhouse API unreachable" | Check `phone_number` and network; the Clubhouse API may be temporarily down |
| Auth token expired | Re-run `python3 auth_setup.py` |
| TTS errors on headless Linux | `sudo apt install espeak-ng` (fallback engine for pyttsx3) |
| No sound in room | Verify the room handshake returned an `agora_channel` (check logs after join) |

## License

MIT
