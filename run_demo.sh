#!/usr/bin/env bash
# Run the ClubDJ Bot in demo mode (fully local, no Clubhouse connection).
set -e
cd "$(dirname "$0")"
source venv/bin/activate
exec python3 main.py --demo
