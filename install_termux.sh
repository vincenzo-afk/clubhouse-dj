#!/usr/bin/env bash
# ==============================================================================
# ClubDJ — Termux (Android) installer
# Sets up everything needed to run the bot on your phone via Termux.
# Recommended: install Termux from F-Droid (not Play Store). Dependencies: python, ffmpeg, yt-dlp, pubnub.
# ==============================================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo "=============================================================="
echo " ClubDJ — Termux installer for Android"
echo "=============================================================="

# 1. Basic Termux packages
echo ""
echo "[$(date +%T)] Updating Termux packages..."
pkg update -y > /dev/null 2>&1 || true
pkg install -y python ffmpeg git wget openssl termux-api > /dev/null 2>&1 || true

# 2. Storage access (so the bot can write downloads next to the repo)
termux-setup-storage > /dev/null 2>&1 || true

# 3. Python venv + dependencies
echo "[$(date +%T)] Creating Python virtual environment..."
python -m venv venv
source venv/bin/activate

# webrtcvad often fails to build on Termux (no C compiler) — install what works
echo "[$(date +%T)] Installing Python dependencies (this may take 3-5 minutes)..."
pip install -q --upgrade pip
# clubhouse-py deps + pubnub + audio pipeline; skip heavy compile-only ones
pip install -q \
  clubhouse-py pubnub requests gTTS pyttsx3 \
  yt-dlp "pydub>=0.25" playsound==1.3.0 \
  pydub apscheduler > /dev/null 2>&1 || true

# Fallback: install whatever remains missing one by one
for pkg in webrtcvad; do
  if ! python -c "import $pkg" 2>/dev/null; then
    pip install -q "$pkg" 2>/dev/null || echo -e "${YELLOW}[warn] $pkg could not compile (non-fatal — silence detection will use RMS-only mode)${NC}"
  fi
done

# 4. espeak-ng for pyttsx3 fallback TTS
command -v espeak > /dev/null 2>&1 || pkg install -y espeak-ng > /dev/null 2>&1 || true

echo ""
echo -e "${GREEN}[done] Dependencies installed.${NC}"

# 5. Quick sanity check
echo ""
echo "[$(date +%T)] Verifying installation..."
source venv/bin/activate 2>/dev/null || true
python -c "
import sys
ok = True
for mod in ['clubhouse', 'pubnub', 'yt_dlp', 'pydub', 'gtts', 'pyttsx3', 'ffmpeg']:
    try:
        if mod == 'ffmpeg':
            import shutil
            if not shutil.which('ffmpeg'): raise ImportError
        else:
            __import__(mod)
        print(f'  OK   {mod}')
    except Exception:
        ok = False
        print(f'  FAIL {mod}')
if not ok:
    print()
    print('Some modules failed. Run: pip install -r requirements.txt')
    print('(or install missing ones individually: pip install <name>)')
    sys.exit(1)
" && echo -e "${GREEN}[done] All core modules verified.${NC}"

echo ""
echo "=============================================================="
echo -e "${GREEN} ClubDJ is ready on your phone!${NC}"
echo ""
echo " Next steps:"
echo "  1. Edit config.json  (nano config.json)"
echo "     - set phone_number and room_id"
echo "  2. Add auth_token.json  (your Clubhouse token)"
echo "  3. Run: ./run_termux.sh"
echo ""
echo " To keep the bot alive when you close Termux:"
echo "  - Settings > Apps > Termux > Battery > set 'Unrestricted'"
echo "  - In Termux notification bar > tap 'Acquire wakelock'"
echo "  - Keep Termux running (or use tmux; see docs/DEPLOY_MOBILE.md)"
echo "=============================================================="
