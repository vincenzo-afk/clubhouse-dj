"""
tests/test_e2e_demo.py — End-to-end demo run of the full bot pipeline.

Mirrors what main.py --demo does, then simulates chat commands to verify the
whole chain: chat -> command handler -> queue -> audio player (download +
stream) -> announcer (TTS).
"""

import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.clubhouse_client import ClubhouseClient
from bot.audio_player import AudioPlayer
from bot.queue_manager import QueueManager
from bot.announcer import Announcer
from bot.command_handler import CommandHandler
from bot.scheduler import Scheduler
from bot.silence_detector import SilenceDetector

CONFIG = {
    "phone_number": "+91XXXXXXXXXX",
    "room_id": "demo-room",
    "silence_threshold_minutes": 1,
    "auto_dj_mode": True,
    "default_genre": "lofi chill",
    "max_song_duration_seconds": 300,
    "max_queue_size": 20,
    "announce_songs": False,
    "skip_votes_required": 3,
    "bot_name": "ClubDJ Test",
    "agora_app_id": "test",
    "agora_token": "",
    "agora_uid": 12345,
    "cache_dir": "./playlist/cache",
    "tts_cache_dir": "./playlist/tts_cache",
    "auth_token_file": "./auth_token.json",
    "log_level": "INFO",
    "ytdlp_format": "bestaudio/best",
    "audio_sample_rate": 16000,
    "audio_channels": 1,
    "audio_frame_ms": 10,
    "reconnect_delay_seconds": 5,
    "max_reconnect_attempts": 10,
    "watchdog_check_interval": 30,
}


def main():
    print("\n" + "=" * 70)
    print("E2E DEMO — Full bot pipeline test (local mode)")
    print("=" * 70)

    chats_out = []

    player = AudioPlayer(CONFIG)
    announcer = Announcer(CONFIG, audio_player=player)
    queue = QueueManager(CONFIG, audio_player=player, announcer=announcer)
    scheduler = Scheduler(CONFIG, queue_manager=queue)
    detector = SilenceDetector(CONFIG, on_silence=queue.trigger_auto_dj)
    detector.start_monitoring(simulated=True)

    client = ClubhouseClient(CONFIG)
    client.room_id = "demo-room"

    handler = CommandHandler(
        CONFIG,
        queue_manager=queue,
        announcer=announcer,
        scheduler=scheduler,
        silence_detector=detector,
        send_chat_fn=lambda m: chats_out.append(m) or print(f"[CHAT OUT] {m}"),
    )

    # --- Scenario 1: user requests a song via chat (short royalty-free track) ---
    print("\n--- Scenario 1: !play request via chat ---")
    handler.handle_message(
        "Listener1",
        "!play https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    )
    time.sleep(6)

    # --- Scenario 2: queue status ---
    print("\n--- Scenario 2: !queue and !np ---")
    handler.handle_message("Listener2", "!queue")
    handler.handle_message("Listener2", "!np")
    time.sleep(1)

    # --- Scenario 3: second song queued ---
    print("\n--- Scenario 3: second song + help ---")
    handler.handle_message("Listener3", "!play Yesterday")
    handler.handle_message("Listener4", "!help")
    time.sleep(1)

    # --- Scenario 4: wait for first song to finish, queue auto-advances ---
    print("\n--- Scenario 4: waiting for first song to finish... ---")
    deadline = time.time() + 30
    while player.is_playing and time.time() < deadline:
        time.sleep(2)
        print(f"  playing={player.is_playing} now: {player.now_playing['title'][:50]}")

    if time.time() >= deadline and player.is_playing:
        print("  (first song is long — stopping it to continue the test)")
        player.stop()

    # --- Scenario 5: TTS announcement generation ---
    print("\n--- Scenario 5: TTS announcement ---")
    wav = announcer._generate_wav("This is the ClubDJ bot speaking.")
    if wav:
        with wave.open(wav, "rb") as wf:
            print(f"  TTS WAV: {wav}, {wf.getnframes()/wf.getframerate():.1f}s, "
                  f"{wf.getframerate()}Hz, {wf.getnchannels()}ch")

    # --- Scenario 6: song-end callback chain ---
    print("\n--- Scenario 6: song-end callback advances queue ---")
    q_before = len(queue.get_queue())
    np_before = queue.get_now_playing()
    handler.handle_message("Listener5", "!skip", is_moderator=True)
    time.sleep(1)
    print(f"  queue entries before skip: {q_before}")
    print(f"  now playing after skip: {queue.get_now_playing()}")

    # --- Scenario 7: silence timer fires (simulated, 60s) ---
    print("\n--- Scenario 7: waiting for simulated silence timer (60s) ---")
    player.stop()
    t0 = time.time()
    fired = False
    while time.time() - t0 < 62:
        time.sleep(3)
        print(f"  silent={detector.is_silent()} elapsed={time.time()-t0:.0f}s")
    print("  (silence timer should have fired an Auto DJ event above)")

    detector.stop_monitoring()
    scheduler.stop()
    player.stop()

    print("\n" + "=" * 70)
    print("E2E demo complete. Total chat replies:", len(chats_out))
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
