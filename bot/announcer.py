"""
announcer.py — Generates TTS announcements via gTTS (with pyttsx3 fallback),
converts them to 16 kHz mono WAV, and injects them into the Agora audio stream
before each song starts.
"""

from __future__ import annotations

import os
import hashlib
import subprocess
import tempfile
import threading
from datetime import datetime


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [ANNOUNCER] {msg}")


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    _log("gTTS not installed — will use pyttsx3 fallback.")

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    _log("pyttsx3 not installed — TTS disabled.")


class Announcer:
    """
    Converts announcement text to audio and streams it via AudioPlayer.
    Uses an LRU-style file cache keyed by MD5 of the announcement text.
    """

    def __init__(self, config: dict, audio_player=None):
        self.config      = config
        self.audio_player = audio_player
        self.tts_cache   = config.get("tts_cache_dir", "./playlist/tts_cache")
        self.sample_rate = config.get("audio_sample_rate", 16000)
        self.announce_songs = config.get("announce_songs", True)
        self._lock = threading.Lock()

        os.makedirs(self.tts_cache, exist_ok=True)
        _log("Announcer initialised.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_wav_path(self, text: str) -> str:
        key = hashlib.md5(text.encode()).hexdigest()
        return os.path.join(self.tts_cache, f"{key}.wav")

    def _is_cached(self, text: str) -> bool:
        return os.path.isfile(self._cache_wav_path(text))

    def _gtts_to_wav(self, text: str, wav_path: str) -> bool:
        """Generate TTS via gTTS → temp MP3 → ffmpeg → WAV."""
        if not GTTS_AVAILABLE:
            return False
        try:
            tmp_mp3 = os.path.join(tempfile.gettempdir(), f"announce_{hashlib.md5(text.encode()).hexdigest()}.mp3")
            tts = gTTS(text=text, lang="en", slow=False)
            tts.save(tmp_mp3)

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", tmp_mp3,
                    "-ar", str(self.sample_rate),
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    wav_path,
                    "-loglevel", "error",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if os.path.isfile(tmp_mp3):
                os.remove(tmp_mp3)

            if result.returncode != 0:
                _log(f"ffmpeg TTS convert error: {result.stderr.strip()}")
                return False
            return True
        except Exception as exc:
            _log(f"gTTS generation error: {exc}")
            return False

    def _pyttsx3_to_wav(self, text: str, wav_path: str) -> bool:
        """Generate TTS via pyttsx3 → WAV file directly."""
        if not PYTTSX3_AVAILABLE:
            return False
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 1.0)
            engine.save_to_file(text, wav_path)
            engine.runAndWait()
            engine.stop()

            # pyttsx3 may write in a non-16kHz format — re-encode with ffmpeg
            tmp = wav_path + ".tmp.wav"
            os.rename(wav_path, tmp)
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", tmp,
                    "-ar", str(self.sample_rate),
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    wav_path,
                    "-loglevel", "error",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if os.path.isfile(tmp):
                os.remove(tmp)
            return result.returncode == 0
        except Exception as exc:
            _log(f"pyttsx3 error: {exc}")
            return False

    def _generate_wav(self, text: str) -> str | None:
        """
        Returns path to a cached WAV file for the given text.
        Tries gTTS first, falls back to pyttsx3.
        """
        with self._lock:
            wav_path = self._cache_wav_path(text)
            if self._is_cached(text):
                return wav_path

            _log(f"Generating TTS: \"{text}\"")

            if GTTS_AVAILABLE and self._gtts_to_wav(text, wav_path):
                return wav_path

            _log("gTTS failed — trying pyttsx3 fallback.")
            if PYTTSX3_AVAILABLE and self._pyttsx3_to_wav(text, wav_path):
                return wav_path

            _log("All TTS backends failed.")
            return None

    def _stream_announcement(self, text: str):
        """Generate wav and push through AudioPlayer synchronously."""
        if not self.audio_player:
            _log(f"[TTS only — no AudioPlayer] {text}")
            return

        wav_path = self._generate_wav(text)
        if not wav_path:
            _log(f"Could not generate TTS for: {text}")
            return

        # Temporarily inject the announcement via the player's stream method
        # (doesn't fire on_song_end callback)
        try:
            self.audio_player._stream_wav(wav_path)
        except Exception as exc:
            _log(f"Announcement stream error: {exc}")

    # ------------------------------------------------------------------
    # Public announcement methods
    # ------------------------------------------------------------------

    def announce(self, text: str, blocking: bool = True):
        """Speak any arbitrary text into the room."""
        if not self.announce_songs:
            return
        if blocking:
            self._stream_announcement(text)
        else:
            t = threading.Thread(
                target=self._stream_announcement,
                args=(text,),
                daemon=True,
                name="announcer-thread",
            )
            t.start()

    def now_playing(self, title: str, requested_by: str):
        text = f"Now playing: {title}, requested by {requested_by}."
        _log(text)
        self.announce(text, blocking=False)

    def auto_dj_activated(self, silence_minutes: int):
        text = (
            f"Auto DJ mode activated. "
            f"Silence detected for {silence_minutes} minutes."
        )
        _log(text)
        self.announce(text, blocking=False)

    def queue_empty(self):
        text = "Queue is empty. Add songs with the play command."
        _log(text)
        self.announce(text, blocking=False)

    def bot_connected(self):
        text = "ClubDJ Bot connected. Ready to play music!"
        _log(text)
        self.announce(text, blocking=False)

    def welcome(self):
        text = "ClubDJ is live! Type exclamation play followed by a song name to request music."
        _log(text)
        self.announce(text, blocking=False)