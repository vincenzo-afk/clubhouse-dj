# ClubDJ on Your Android Phone (Termux)

Run the full ClubDJ bot directly on your iQOO Z10 using [Termux](https://termux.dev), a Linux terminal emulator for Android. No root, no PC, no cloud costs — your phone *is* the server.

> **Honest expectations:** this is a free, convenient way to test and run the bot, but a phone is not an ideal 24/7 server. Android's battery optimization can kill Termux in the background, and the phone warms up during audio encoding. It comfortably runs for hours (and often all night) with the battery settings below; for true always-on hosting, Render or a VPS is better.

---

## 1. Install Termux

Install Termux from **F-Droid** or the [official GitHub releases](https://github.com/termux/termux-app/releases) — **not** the Play Store version (it is outdated and broken).

Open Termux and grant storage permission:

```bash
termux-setup-storage
```

## 2. Clone and install

```bash
pkg install -y git
git clone https://github.com/vincenzo-afk/clubhouse-dj.git
cd clubhouse-dj
chmod +x install_termux.sh run_termux.sh
./install_termux.sh
```

`install_termux.sh` installs Python, ffmpeg, yt-dlp, and all bot dependencies inside a virtual environment. If `webrtcvad` fails to compile (no C compiler on Termux), the bot automatically falls back to RMS-only silence detection — no action needed.

## 3. Configure

```bash
nano config.json       # set phone_number and room_id
```

Add your Clubhouse token (`auth_token.json`) — see the main README **Authentication** section. On the phone, you can log into the Clubhouse app (Google sign-in) and capture the `CH-Auth` token via the Packet Capture app you already have, or paste the values you captured earlier.

## 4. Run the bot

```bash
./run_termux.sh        # foreground — works while Termux is open
./run_termux.sh tmux   # inside tmux — survives closing Termux
./run_termux.sh logs   # follow the log
./run_termux.sh stop   # stop the bot
```

## 5. Keep it alive (important)

Android aggressively kills background apps. Do all three of these:

| Step | Where | What to set |
|---|---|---|
| Battery optimization | Settings → Apps → Termux → Battery | **Unrestricted** (allow background activity) |
| Wake lock | Termux notification bar (swipe down) | Tap **Acquire wakelock** — shows a permanent notification |
| Lock screen | Termux → Settings → Wake lock | Enable (prevents sleep throttling) |

On Vivo/iQOO (Funtouch OS), also enable **Auto-start** for Termux: Settings → Apps → Special app access → Auto-start → Termux → ON.

With these settings, the bot can run overnight. If the phone reboots or Termux is force-killed, reopen Termux and run `./run_termux.sh tmux` again (the tmux session persists while the Termux app process is alive).

## 6. Test without an account first

```bash
./venv/bin/python main.py --demo
```

Runs the complete pipeline locally with simulated chat — song download, streaming, announcements, skip voting, silence timer, and Auto DJ.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip` fails on `webrtcvad` | Non-fatal — bot uses RMS-only silence detection |
| Bot dies after screen-off | Enable Unrestricted battery + wake lock (Step 5) |
| "ffmpeg not found" | `pkg install -y ffmpeg` |
| yt-dlp blocked by YouTube | Use direct audio URLs (`!play <URL>`) or add `cookies.txt` next to `main.py` |
| TTS errors on Termux | `pkg install -y espeak-ng` (already done by install script) |
| Network stops when screen off | Keep the Termux wake-lock notification active; some carriers also pause mobile data when idle |
