#!/usr/bin/env bash
# Verify the install flow works end-to-end on this environment.
set -e
cd /home/ubuntu/clubhouse-dj
mkdir -p logs playlist/cache playlist/tts_cache
source venv/bin/activate
pip install -q -r requirements.txt && echo "DEPS OK"
# Quick smoke test: start bot in demo mode for 10s
timeout 10 python3 main.py --demo >/dev/null 2>&1 && echo "DEMO BOOT OK"
