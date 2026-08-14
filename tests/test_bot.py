"""
tests/test_bot.py — Comprehensive local tests for all ClubDJ components.

Runs without any Clubhouse/Agora credentials:
  1. AudioPlayer — download + convert + stream a short track (local mode)
  2. Announcer — generate TTS announcement WAVs via gTTS + ffmpeg
  3. QueueManager — enqueue, autoplay, song-end callback, Auto DJ fallback
  4. CommandHandler — parse and dispatch all chat commands
  5. Scheduler — silence countdown triggers auto DJ
  6. SilenceDetector — RMS computation + simulated silence timer
  7. ClubhouseClient — API health check + login verification (read-only)
"""

import json
import os
import sys
import time
import unittest
import wave
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.audio_player import AudioPlayer
from bot.announcer import Announcer
from bot.queue_manager import QueueManager
from bot.command_handler import CommandHandler
from bot.scheduler import Scheduler
from bot.silence_detector import SilenceDetector
from bot.clubhouse_client import ClubhouseClient


CONFIG = {
    "phone_number": "+91XXXXXXXXXX",
    "room_id": "test-room",
    "silence_threshold_minutes": 1,
    "auto_dj_mode": True,
    "default_genre": "lofi chill",
    "max_song_duration_seconds": 300,
    "max_queue_size": 20,
    "announce_songs": False,   # keep tests fast/quiet
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


class TestAudioPlayer(unittest.TestCase):
    def setUp(self):
        self.finished = []
        self.player = AudioPlayer(CONFIG, on_song_end=lambda t, r: self.finished.append((t, r)))

    def test_download_short_track(self):
        """Download a very short royalty-free track, convert to WAV, and stream it."""
        ok = self.player.play(
            "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
            requested_by="Tester",
        )
        # Give it a few seconds to download + convert
        time.sleep(8)
        self.assertTrue(self.player.is_playing, "Playback should have started")
        self.assertTrue(
            self.player.now_playing["title"].endswith("SoundHelix-Song-1.mp3"),
            f"Unexpected title: {self.player.now_playing['title']}",
        )

    def test_download_invalid_query_returns_false(self):
        ok = self.player.play("this song definitely does not exist xyz123",
                              requested_by="Tester")
        time.sleep(5)
        self.assertFalse(ok, "Invalid query should fail gracefully")

    def test_cache_hit(self):
        query = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
        self.player.play(query, requested_by="Tester")
        time.sleep(6)
        # Should find a cached .wav in the cache dir
        cache_files = [f for f in os.listdir(CONFIG["cache_dir"]) if f.endswith(".wav")]
        self.assertGreater(len(cache_files), 0, "WAV cache should contain files")

    def test_pause_resume_stop(self):
        ok = self.player.play(
            "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
            requested_by="Tester",
        )
        # Wait until playback actually starts (download + convert first)
        deadline = time.time() + 60
        while not self.player.is_playing and time.time() < deadline:
            time.sleep(1)
        self.assertTrue(self.player.is_playing, "Playback should have started")
        self.player.pause()
        self.assertTrue(self.player.is_paused)
        self.player.resume()
        self.assertFalse(self.player.is_paused)
        self.player.stop()
        self.assertFalse(self.player.is_playing)

    def tearDown(self):
        self.player.stop()


class TestAnnouncer(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(CONFIG)
        self.announcer = Announcer(CONFIG, audio_player=self.player)

    def test_generate_tts_wav(self):
        wav = self.announcer._generate_wav("Hello, this is a test announcement.")
        self.assertIsNotNone(wav, "gTTS should produce a WAV file")
        self.assertTrue(os.path.isfile(wav))
        with wave.open(wav, "rb") as wf:
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnchannels(), 1)

    def test_tts_caching(self):
        text = "Cached announcement test"
        p1 = self.announcer._generate_wav(text)
        p2 = self.announcer._generate_wav(text)
        self.assertEqual(p1, p2, "Same text must return the cached path")

    def tearDown(self):
        self.player.stop()


class TestQueueManager(unittest.TestCase):
    def setUp(self):
        self.events = []
        # The mock reports is_playing=True once playback has "started",
        # so the queue does not drain instantly on every add.
        self.player = MagicMock()
        self.player.is_playing = False
        self.player.play.return_value = True

        def mark_playing(*a, **kw):
            self.player.is_playing = True
            return True

        self.player.play.side_effect = mark_playing
        self.player.skip.side_effect = lambda: None
        self.announcer = MagicMock()
        self.queue = QueueManager(CONFIG, audio_player=self.player,
                                  announcer=self.announcer)

    def test_add_song_starts_playback(self):
        result = self.queue.add_song("Bohemian Rhapsody", requested_by="Alice")
        self.assertIn("position 1", result)
        self.player.play.assert_called_once()

    def test_queue_fills_in_order(self):
        # add_song immediately starts playback of the first song, so only
        # the remaining two stay in the queue. Ordering is still preserved.
        self.queue.add_song("Song A")
        self.queue.add_song("Song B")
        self.queue.add_song("Song C")
        q = self.queue.get_queue()
        self.assertEqual(len(q), 2)
        self.assertEqual(q[0]["query"], "Song B")
        self.assertEqual(q[1]["query"], "Song C")

    def test_queue_capacity(self):
        for i in range(CONFIG["max_queue_size"] + 1):
            self.queue.add_song(f"Song {i}")
        self.assertEqual(len(self.queue.get_queue()), CONFIG["max_queue_size"])

    def test_on_song_end_pulls_next(self):
        self.queue.add_song("First")
        self.queue.add_song("Second")
        # Simulate first song ending (callback wired by QueueManager)
        self.player.on_song_end("First", "Auto DJ")
        # play() should have been called twice
        self.assertEqual(self.player.play.call_count, 2)

    def test_auto_dj_fallback(self):
        self.queue.trigger_auto_dj()
        self.assertTrue(self.player.play.called, "Auto DJ should play a default song")

    def test_clear_queue(self):
        self.queue.add_song("X")   # starts playing immediately (drains queue)
        self.queue.add_song("Y")   # waits in the queue
        result = self.queue.clear_queue()
        self.assertIn("1 songs", result)
        self.assertEqual(len(self.queue.get_queue()), 0)

        # Clearing again on an empty queue should still be safe
        result2 = self.queue.clear_queue()
        self.assertIn("0 songs", result2)


class TestCommandHandler(unittest.TestCase):
    def setUp(self):
        self.chats = []
        self.player = MagicMock()
        self.player.is_playing = False
        self.player.play.return_value = True

        def mark_playing(*a, **kw):
            self.player.is_playing = True
            return True

        self.player.play.side_effect = mark_playing
        self.player.skip.side_effect = lambda: None
        self.queue = QueueManager(CONFIG, audio_player=self.player)
        self.scheduler = MagicMock()
        self.detector = MagicMock()
        self.cmd = CommandHandler(
            CONFIG,
            queue_manager=self.queue,
            scheduler=self.scheduler,
            silence_detector=self.detector,
            send_chat_fn=lambda m: self.chats.append(m),
        )

    def test_play_command(self):
        self.cmd.handle_message("Alice", "!play Lofi Girl")
        self.assertTrue(any("position 1" in c for c in self.chats))

    def test_play_without_argument(self):
        self.cmd.handle_message("Alice", "!play")
        self.assertTrue(any("Usage" in c for c in self.chats))

    def test_skip_votes(self):
        self.queue.add_song("Song", requested_by="Tester")
        self.chats.clear()
        self.cmd.handle_message("Alice", "!skip")
        self.cmd.handle_message("Bob", "!skip")
        self.assertTrue(any("1/3" in c for c in self.chats) or
                        any("2/3" in c for c in self.chats))
        self.assertFalse(self.player.skip.called)
        self.cmd.handle_message("Charlie", "!skip")
        self.assertTrue(self.player.skip.called)
        self.player.skip.reset_mock()
        self.player.is_playing = False

    def test_mod_skip_instant(self):
        self.queue.add_song("Song", requested_by="Tester")
        self.cmd.handle_message("Moderator", "!skip", is_moderator=True)
        self.assertTrue(self.player.skip.called)
        self.player.is_playing = False

    def test_queue_command(self):
        self.cmd.handle_message("Alice", "!play Song 1")
        self.chats.clear()
        self.cmd.handle_message("Bob", "!queue")
        self.assertTrue(any("Queue" in c for c in self.chats))

    def test_np_command(self):
        self.queue.add_song("Test Song")
        self.chats.clear()
        self.cmd.handle_message("Alice", "!np")
        self.assertTrue(any("Now playing" in c for c in self.chats))

    def test_timer_mod_only(self):
        self.cmd.handle_message("Regular", "!timer 15")
        self.assertTrue(any("Only moderators" in c for c in self.chats))
        self.chats.clear()
        self.cmd.handle_message("Mod", "!timer 15", is_moderator=True)
        self.assertTrue(any("15 minutes" in c for c in self.chats))

    def test_stop_requires_mod(self):
        self.cmd.handle_message("Regular", "!stop")
        self.assertTrue(any("Only moderators" in c for c in self.chats))
        self.cmd.handle_message("Mod", "!stop", is_moderator=True)
        self.assertTrue(any("Auto DJ stopped" in c for c in self.chats))

    def test_help_command(self):
        self.cmd.handle_message("Alice", "!help")
        self.assertTrue(any("ClubDJ Commands" in c for c in self.chats))

    def test_unknown_command(self):
        self.cmd.handle_message("Alice", "!foo")
        self.assertTrue(any("Unknown command" in c for c in self.chats))

    def test_non_command_ignored(self):
        self.cmd.handle_message("Alice", "Hello everyone!")
        self.assertEqual(len(self.chats), 0)


class TestScheduler(unittest.TestCase):
    def test_fires_after_threshold(self):
        cfg = dict(CONFIG, silence_threshold_minutes=1)
        qm = MagicMock()
        sched = Scheduler(cfg, queue_manager=qm)
        sched.start()
        time.sleep(65)
        qm.trigger_auto_dj.assert_called()
        sched.stop()


class TestSilenceDetector(unittest.TestCase):
    def test_rms_computation(self):
        import numpy as np
        # Loud signal
        loud = (np.random.RandomState(0).randn(32000) * 10000).astype("<i2").tobytes()
        self.assertGreater(SilenceDetector._compute_rms(loud), 1000)
        # Silent signal
        silent = b"\x00\x00" * 16000
        self.assertAlmostEqual(SilenceDetector._compute_rms(silent), 0.0)

    def test_simulated_monitor_triggers(self):
        triggered = []
        cfg = dict(CONFIG, silence_threshold_minutes=1)
        det = SilenceDetector(cfg, on_silence=lambda: triggered.append(True))
        det.start_monitoring(simulated=True)
        time.sleep(63)
        self.assertGreater(len(triggered), 0,
                           "Simulated silence timer should have fired")
        det.stop_monitoring()


class TestClubhouseClient(unittest.TestCase):
    def test_api_health_check(self):
        """Read-only sanity check that Clubhouse API is reachable."""
        try:
            resp = ClubhouseClient.check_for_update()
            self.assertIsInstance(resp, dict)
        except Exception as exc:
            self.skipTest(f"Clubhouse API unreachable: {exc}")

    def test_unauthenticated_login_rejected(self):
        """Login with a fake token should fail verification (read-only test)."""
        client = ClubhouseClient(CONFIG)
        with self.assertRaises(Exception):
            client.login(user_id="0", user_token="invalid-token", device_id="0")

    def test_join_without_login_raises(self):
        client = ClubhouseClient(CONFIG)
        with self.assertRaises(RuntimeError):
            client.join_room("test-room")


if __name__ == "__main__":
    unittest.main(verbosity=2)
