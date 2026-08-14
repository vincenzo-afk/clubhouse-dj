#!/usr/bin/env bash
# ============================================================================
# ClubDJ Bot — start / stop / status script
#
# Works with or without systemd:
#   ./start.sh            — start the bot (foreground, use in a screen/tmux
#                           session on macOS or for debugging)
#   ./start.sh --daemon   — start in background (nohup)
#   ./start.sh --demo     — run in demo mode (no Clubhouse, local-only)
#   ./stop.sh             — stop a backgrounded instance
#   ./status.sh           — show whether the bot is running
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
PID_FILE="./clubdj.pid"
LOG_FILE="./logs/clubdj.log"

mkdir -p logs

start_bg() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Bot is already running (PID $(cat "$PID_FILE"))."
        exit 0
    fi
    source venv/bin/activate
    nohup python3 main.py "$@" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Bot started in background (PID $!). Logs: $LOG_FILE"
}

stop_bg() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "Bot stopped (PID $PID)."
        else
            echo "PID $PID is not running (stale pid file removed)."
        fi
        rm -f "$PID_FILE"
    else
        echo "No pid file found — bot may not be running."
        pkill -f "python3 main.py" && echo "Background python3 main.py processes killed." || true
    fi
}

show_status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Bot is RUNNING (PID $(cat "$PID_FILE"))."
        echo "Logs:"
        tail -n 15 "$LOG_FILE"
    else
        echo "Bot is NOT running."
    fi
}

case "${1:-start}" in
    --daemon|daemon)  shift; start_bg "$@" ;;
    --stop|stop)      stop_bg ;;
    --status|status)  show_status ;;
    --logs|logs)      tail -f "$LOG_FILE" ;;
    *)                start_bg "$@" ;;
esac
