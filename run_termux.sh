#!/usr/bin/env bash
# ==============================================================================
# ClubDJ — run on Termux (Android)
#
# Usage:
#   ./run_termux.sh          # run in foreground (keep Termux open)
#   ./run_termux.sh tmux     # run inside tmux so it survives closing Termux
#   ./run_termux.sh stop     # stop the tmux session
#   ./run_termux.sh logs     # follow the log
# ==============================================================================
set -e
cd "$(dirname "$0")"

MODE="${1:-run}"

case "$MODE" in
  run)
    echo "Starting ClubDJ in foreground..."
    exec ./venv/bin/python main.py
    ;;

  tmux)
    if ! command -v tmux > /dev/null 2>&1; then
      echo "Installing tmux..."
      pkg install -y tmux > /dev/null 2>&1
    fi
    if tmux has-session -t clubdj 2>/dev/null; then
      echo "ClubDJ is already running in a tmux session."
      echo "Reattach with: tmux attach -t clubdj"
      exit 0
    fi
    echo "Starting ClubDJ inside tmux (survives closing Termux)..."
    tmux new-session -d -s clubdj "./venv/bin/python main.py 2>&1 | tee -a logs/bot.log"
    echo "Bot started. Keep Termux alive + wakelock for it to stay running."
    echo "  Reattach:   tmux attach -t clubdj"
    echo "  Stop:       ./run_termux.sh stop"
    echo "  Logs:       ./run_termux.sh logs"
    ;;

  stop)
    tmux kill-session -t clubdj 2>/dev/null && echo "ClubDJ stopped." || echo "Not running."
    ;;

  logs)
    tail -f logs/bot.log 2>/dev/null || echo "No log yet (logs/bot.log)."
    ;;

  *)
    echo "Usage: $0 {run|tmux|stop|logs}"
    exit 1
    ;;
esac
