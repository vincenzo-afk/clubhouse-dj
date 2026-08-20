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

# Install dependencies — one package per line so failures are visible.
echo "[$(date +%T)] Installing Python dependencies (this may take 3-5 minutes)..."
pip install --upgrade pip 2>&1 | tail -1

PIP_PACKAGES=(
  clubhouse-py
  pubnub
  requests
  gTTS
  pyttsx3
  yt-dlp
  "pydub>=0.25"
  apscheduler
)

FAILED=0
for pkg in "${PIP_PACKAGES[@]}"; do
  if python -c "import ${pkg%%[>=]*}" 2>/dev/null; then
    echo "  OK   $pkg (already installed)"
    continue
  fi
  echo -n "  installing $pkg ... "
  if pip install -q "$pkg" > /tmp/clubdj_pip_$RANDOM.log 2>&1; then
    echo "OK"
  else
    echo "FAILED (see /tmp/clubdj_pip_*.log)"
    FAILED=1
  fi
done

# webrtcvad often fails to build on Termux (no C compiler) — non-fatal
if ! python -c "import webrtcvad" 2>/dev/null; then
  echo -n "  installing webrtcvad ... "
  pip install -q webrtcvad > /dev/null 2>&1 && echo "OK" || \
    echo -e "${YELLOW}skipped (non-fatal — silence detection uses RMS-only mode)${NC}"
fi

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo -e "${RED}[error] Some packages failed to install.${NC}"
  echo "Try installing the missing ones manually: pip install <package>"
  echo "If a package fails with a compiler error, tell us the error and we'll find a workaround."
  exit 1
fi

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
