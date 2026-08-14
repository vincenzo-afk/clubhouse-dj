"""
main.py — Entry point for the ClubDJ Bot.

Wires all components together:
    ClubhouseClient (API + PubNub chat)
      -> CommandHandler  -> QueueManager -> AudioPlayer
      -> Announcer (TTS before each song)
      -> Scheduler (silence countdown) + SilenceDetector (RMS-based)

Usage:
    python main.py                    # normal mode (connects to Clubhouse)
    python main.py --demo             # demo mode (no Clubhouse, local-only)
    python main.py --simulate-silence # demo with simulated silence timer
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from bot.clubhouse_client import ClubhouseClient
from bot.audio_player import AudioPlayer
from bot.queue_manager import QueueManager
from bot.announcer import Announcer
from bot.command_handler import CommandHandler
from bot.scheduler import Scheduler
from bot.silence_detector import SilenceDetector


def load_config():
    with open("config.json", "r") as f:
        return json.load(f)


def load_auth(config: dict):
    """
    Load stored auth token, or guide the user through first-time setup.
    Tokens are stored in ./auth_token.json after first login.
    """
    token_file = config.get("auth_token_file", "./auth_token.json")

    if os.path.isfile(token_file):
        with open(token_file, "r") as f:
            stored = json.load(f)
        logger.info("Loaded stored auth token.")
        return stored

    print("=" * 70)
    print("FIRST-TIME SETUP — Clubhouse authentication")
    print("=" * 70)
    print(
        "ClubDJ needs a Clubhouse auth token to join rooms. Obtain it once\n"
        "by running:  python auth_setup.py   (walks you through phone auth\n"
        "and stores the token in auth_token.json).\n"
        "Alternatively, place your user_id / user_token / device_id in\n"
        "auth_token.json manually.\n"
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ClubDJ Bot for Clubhouse")
    parser.add_argument("--demo", action="store_true",
                        help="Run in demo mode without connecting to Clubhouse")
    parser.add_argument("--simulate-silence", action="store_true",
                        help="Demo mode with a simulated (fast) silence timer")
    args = parser.parse_args()

    config = load_config()
    logger.info("Starting ClubDJ Bot...")

    sent_messages = []  # log of what the bot said (for demo mode)

    # ------------------------------------------------------------------
    # 1. Audio player (downloads via yt-dlp, streams to Agora or locally)
    # ------------------------------------------------------------------
    queue = None
    announcer = None
    scheduler = None
    detector = None
    cmd_handler = None

    player = AudioPlayer(config, on_song_end=None)

    # ------------------------------------------------------------------
    # 2. Announcer (TTS before songs)
    # ------------------------------------------------------------------
    announcer = Announcer(config, audio_player=player)

    # ------------------------------------------------------------------
    # 3. Queue manager (wires player.on_song_end automatically)
    # ------------------------------------------------------------------
    queue = QueueManager(config, audio_player=player, announcer=announcer)

    # ------------------------------------------------------------------
    # 4. Scheduler (wall-clock silence countdown → auto DJ)
    # ------------------------------------------------------------------
    scheduler = Scheduler(config, queue_manager=queue)
    if not args.demo:
        scheduler.start()

    # ------------------------------------------------------------------
    # 5. Silence detector (RMS-based, optional real-time feed)
    # ------------------------------------------------------------------
    detector = SilenceDetector(config, on_silence=queue.trigger_auto_dj)
    if args.simulate_silence:
        detector.start_monitoring(simulated=True)
    elif args.demo:
        detector.start_monitoring(simulated=True)

    # ------------------------------------------------------------------
    # 6. Clubhouse client (auth, join room, PubNub chat)
    # ------------------------------------------------------------------
    client = ClubhouseClient(config)

    def on_room_message(username: str, message: str, is_moderator: bool):
        cmd_handler.handle_message(username, message, is_moderator)

    if args.demo:
        def demo_send_chat(msg: str):
            print(f"[CHAT OUT] {msg}")
            sent_messages.append(msg)

        # Demo mode: everything works locally, no Clubhouse connection
        cmd_handler = CommandHandler(
            config,
            queue_manager=queue,
            announcer=announcer,
            scheduler=scheduler,
            silence_detector=detector,
            send_chat_fn=demo_send_chat,
        )
        client.room_id = "demo-room"
        logger.info(
            "DEMO MODE — bot fully operational locally. "
            "Simulate chat with: cmd_handler.handle_message('You', '!play song')"
        )
    else:
        auth = load_auth(config)
        client.login(
            user_id=auth["user_id"],
            user_token=auth["user_token"],
            device_id=auth.get("device_id", ""),
        )
        client.on_message = on_room_message
        client.join_room(config.get("room_id", ""))

        # Once joined, connect audio to the room's Agora channel
        if client.agora_channel:
            player.connect_agora(
                app_id=config.get("agora_app_id", ""),
                channel=client.agora_channel,
                uid=client.agora_uid or config.get("agora_uid", 0),
                token=client.agora_token or config.get("agora_token", ""),
            )

        cmd_handler = CommandHandler(
            config,
            queue_manager=queue,
            announcer=announcer,
            scheduler=scheduler,
            silence_detector=detector,
            send_chat_fn=client.send_chat,
        )

        announcer.bot_connected()
        announcer.welcome()

    # ------------------------------------------------------------------
    # 7. Main loop — watchdog + graceful shutdown
    # ------------------------------------------------------------------
    running = threading.Event()
    running.set()

    def shutdown(signum=None, frame=None):
        logger.info("Shutting down...")
        running.clear()
        client.leave_room()
        scheduler.stop()
        detector.stop_monitoring()
        player.stop()
        if signum:
            sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    watchdog_interval = config.get("watchdog_check_interval", 30)
    reconnect_delay = config.get("reconnect_delay_seconds", 5)
    max_attempts = config.get("max_reconnect_attempts", 10)
    attempt = 0

    logger.info("Bot components initialized. Bot is live.")

    while running.is_set():
        # Auto-DJ: if nothing is playing and queue is empty, start defaults
        if queue and queue.audio_player and not queue.audio_player.is_playing:
            if not queue.get_queue() and queue._auto_dj_active:
                queue.trigger_auto_dj()

        # Reconnect logic (non-demo only)
        if not args.demo and client and not client.room_id:
            attempt += 1
            if attempt > max_attempts:
                logger.error("Max reconnect attempts reached. Exiting.")
                shutdown()
                break
            logger.info(
                f"Reconnecting to Clubhouse (attempt {attempt}/{max_attempts})..."
            )
            try:
                client.join_room(config.get("room_id", ""))
                attempt = 0
            except Exception as exc:
                logger.error(f"Reconnect failed: {exc}")
                time.sleep(reconnect_delay)
        else:
            attempt = 0

        # Keepalive ping for Clubhouse presence
        if not args.demo and client and client.room_id:
            try:
                client.active_ping()
            except Exception as exc:
                logger.warning(f"Keepalive ping failed: {exc}")

        time.sleep(watchdog_interval)

    shutdown()


if __name__ == "__main__":
    main()
