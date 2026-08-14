#!/usr/bin/env bash
# ============================================================================
# ClubDJ Bot — one-command install script (Linux / macOS)
#
# Installs all system dependencies, creates a virtual environment, installs
# Python packages, and sets up the bot to auto-start on boot via systemd
# (Linux only — see start.sh for macOS / manual start).
#
# Usage:
#     chmod +x install.sh start.sh
#     ./install.sh
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ">>> ClubDJ Bot installer"

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
if command -v apt-get &> /dev/null; then
    echo ">>> Installing system packages (apt)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq ffmpeg python3-dev python3-venv \
        portaudio19-dev build-essential >/dev/null
elif command -v dnf &> /dev/null; then
    echo ">>> Installing system packages (dnf)..."
    sudo dnf install -y ffmpeg python3-devel python3-virtualenv \
        portaudio-devel gcc gcc-c++ >/dev/null
elif command -v brew &> /dev/null; then
    echo ">>> Installing system packages (brew)..."
    brew install ffmpeg portaudio >/dev/null
else
    echo ">>> WARNING: No known package manager found. Please install ffmpeg"
    echo "    and portaudio manually, then re-run this script."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
echo ">>> Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade -q pip

echo ">>> Installing Python packages..."
pip install -q -r requirements.txt

# ---------------------------------------------------------------------------
# 3. Create required directories
# ---------------------------------------------------------------------------
mkdir -p playlist/cache playlist/tts_cache logs

# ---------------------------------------------------------------------------
# 4. systemd service (Linux only, optional)
# ---------------------------------------------------------------------------
if command -v systemctl &> /dev/null; then
    echo ">>> Setting up systemd service (auto-start on boot)..."
    sudo cp systemd/clubdj.service /etc/systemd/system/
    # Point the service at this directory and venv
    sudo sed -i "s|__INSTALL_DIR__|$SCRIPT_DIR|g" /etc/systemd/system/clubdj.service
    sudo systemctl daemon-reload
    sudo systemctl enable clubdj
    echo ">>> systemd service 'clubdj' enabled."
    echo "    Start/stop with:  sudo systemctl start|stop clubdj"
    echo "    Logs:             journalctl -u clubdj -f"
else
    echo ">>> No systemd found — the bot will be started manually."
    echo "    Run:  ./start.sh"
fi

echo ""
echo "=============================================="
echo "  Install complete!"
echo "=============================================="
echo ""
echo "NEXT STEP — authentication:"
echo "  1. Edit config.json  (set phone_number + room_id)"
echo "  2. Get a Clubhouse auth token:"
echo "       python auth_setup.py"
echo "     (stores it in auth_token.json)"
echo "  3. Start the bot:"
echo "       ./start.sh"
echo ""
