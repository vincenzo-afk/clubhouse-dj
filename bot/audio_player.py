"""
audio_player.py — Downloads audio via yt-dlp, converts with ffmpeg,
and streams into an Agora RTC room as a custom PCM audio source.
"""

import os
import time
import hashlib
import subprocess
import threading
import wave
import numpy as np
from datetime import datetime

# ---------------------------------------------------------------------------
# Logging helper (mirrors the format used across all modules)
# ---------------------------------------------------------------------------

def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [AUDIO] {msg}")


# ---------------------------------------------------------------------------
# Try to import Agora SDK — graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    from agora_python_sdk import (
        AgoraService,
        AgoraServiceConfig,
        AudioFrame,
        AudioFrameObserver,
    )
    AGORA_AVAILABLE = True
except ImportError:
    AGORA_AVAILABLE = False
    _log("WARNING: agora-python-sdk not installed. Audio will play locally only.")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE   = 16_000   # Hz
CHANNELS      = 1
FRAME_MS      = 10       # milliseconds per push frame
FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) // 1000   # 160 samples per frame
FRAME_BYTES   = FRAME_SAMPLES * 2 * CHANNELS        # int16 → 2 bytes each


class AudioPlayer:
    """
    Manages the entire audio lifecycle:
      download → convert → cache → stream to Agora → callback on finish
    """

    def __init__(self, config: dict, on_song_end=None):
        self.config         = config
        self.cache_dir      = config.get("cache_dir", "./playlist/cache")
        self.max_duration   = config.get("max_song_duration_seconds", 600)
        self.sample_rate    = config.get("audio_sample_rate", SAMPLE_RATE)
        self.on_song_end    = on_song_end   # callable(title, requested_by)

        # Playback state
        self._current_title    = ""
        self._current_req_by   = ""
        self._is_playing       = False
        self._is_paused        = False
        self._stop_event       = threading.Event()
        self._playback_thread  = None

        # Agora
        self._agora_service    = None
        self._audio_sender     = None

        os.makedirs(self.cache_dir, exist_ok=True)
        _log("AudioPlayer initialised.")

    # ------------------------------------------------------------------
    # Agora connection
    # ------------------------------------------------------------------

    def connect_agora(self, app_id: str, channel: str, uid: int, token: str = ""):
        """Initialise Agora service and join channel as audio publisher."""
        if not AGORA_AVAILABLE:
            _log("Agora SDK not available — skipping RTC connect.")
            return

        try:
            cfg = AgoraServiceConfig()
            cfg.app_id      = app_id
            cfg.enable_audio = True

            self._agora_service = AgoraService()
            self._agora_service.initialize(cfg)

            rtc_cfg = self._agora_service.create_rtc_connection_config()
            self._connection = self._agora_service.create_rtc_connection(rtc_cfg)
            self._connection.connect(token, channel, str(uid))

            local_user = self._connection.get_local_user()
            local_user.set_user_role(1)   # broadcaster

            self._audio_sender = local_user.create_audio_track()
            self._audio_sender.set_enabled(True)

            _log(f"Connected to Agora channel '{channel}' as UID {uid}.")
        except Exception as exc:
            _log(f"Agora connection error: {exc}")
            self._agora_service = None

    def disconnect_agora(self):
        if self._agora_service:
            try:
                self._connection.disconnect()
                self._agora_service.release()
                _log("Agora disconnected.")
            except Exception as exc:
                _log(f"Agora disconnect error: {exc}")
            finally:
                self._agora_service = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_path(self, query: str) -> str:
        key = hashlib.md5(query.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{key}.wav")

    def _is_cached(self, query: str) -> bool:
        return os.path.isfile(self._cache_path(query))

    # ------------------------------------------------------------------
    # Download + convert
    # ------------------------------------------------------------------

    def _download_audio(self, query: str) -> str | None:
        """
        Downloads audio from YouTube using yt-dlp as a subprocess.
        Returns the path to the cached WAV file, or None on failure.
        """
        wav_path = self._cache_path(query)
        if self._is_cached(query):
            _log(f"Cache hit: {query}")
            return wav_path

        # Determine search term vs direct URL
        if query.startswith("http://") or query.startswith("https://"):
            yt_query = query
        else:
            yt_query = f"ytsearch1:{query}"

        raw_path = wav_path.replace(".wav", ".raw_download")

        _log(f"Downloading: {yt_query}")

        # Step 1 — yt-dlp download best audio
        ytdlp_cmd = [
            "yt-dlp",
            "--no-playlist",
            "--max-filesize", "50m",
            "--match-filter", f"duration < {self.max_duration}",
            "-f", "bestaudio/best",
            "-o", raw_path,
            "--quiet",
            "--no-warnings",
            yt_query,
        ]

        try:
            result = subprocess.run(
                ytdlp_cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                _log(f"yt-dlp error: {result.stderr.strip()}")
                return None
        except subprocess.TimeoutExpired:
            _log("yt-dlp timed out after 120 seconds.")
            return None
        except FileNotFoundError:
            _log("yt-dlp not found. Install it: pip install yt-dlp")
            return None

        # Locate whatever file yt-dlp wrote (extension may vary)
        actual_raw = None
        for f in os.listdir(self.cache_dir):
            candidate = os.path.join(self.cache_dir, f)
            if candidate.startswith(raw_path.rstrip("x")):
                actual_raw = candidate
                break
        if not actual_raw:
            # yt-dlp wrote exactly raw_path or with extension
            for ext in ["", ".webm", ".m4a", ".opus", ".mp3", ".ogg"]:
                if os.path.isfile(raw_path + ext):
                    actual_raw = raw_path + ext
                    break

        if not actual_raw or not os.path.isfile(actual_raw):
            _log("Downloaded file not found after yt-dlp run.")
            return None

        # Step 2 — ffmpeg convert to 16 kHz mono PCM WAV
        _log(f"Converting to WAV: {actual_raw}")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", actual_raw,
            "-ar", str(self.sample_rate),
            "-ac", str(CHANNELS),
            "-acodec", "pcm_s16le",
            wav_path,
            "-loglevel", "error",
        ]

        try:
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                _log(f"ffmpeg error: {result.stderr.strip()}")
                if os.path.isfile(actual_raw):
                    os.remove(actual_raw)
                return None
        except subprocess.TimeoutExpired:
            _log("ffmpeg timed out.")
            return None
        except FileNotFoundError:
            _log("ffmpeg not found. Install via: sudo apt install ffmpeg")
            return None

        # Clean up raw download
        try:
            if actual_raw != wav_path and os.path.isfile(actual_raw):
                os.remove(actual_raw)
        except OSError:
            pass

        _log(f"Audio ready: {wav_path}")
        return wav_path

    # ------------------------------------------------------------------
    # Playback helpers
    # ------------------------------------------------------------------

    def _push_audio_frame(self, pcm_bytes: bytes):
        """Push one 10 ms PCM frame to Agora (or stdout for local debug)."""
        if self._audio_sender and AGORA_AVAILABLE:
            try:
                frame = AudioFrame()
                frame.samples_per_sec   = self.sample_rate
                frame.channels          = CHANNELS
                frame.samples_per_channel = FRAME_SAMPLES
                frame.bytes_per_sample  = 2
                frame.buffer            = pcm_bytes
                self._audio_sender.push_audio_pcm_data(frame)
            except Exception as exc:
                _log(f"Agora push error: {exc}")

    def _stream_wav(self, wav_path: str):
        """
        Reads the WAV file in 10 ms chunks and pushes each frame to Agora
        at real-time pace.  Honors pause / stop events.
        """
        try:
            with wave.open(wav_path, "rb") as wf:
                n_channels  = wf.getnchannels()
                sampwidth   = wf.getsampwidth()
                framerate   = wf.getframerate()

                # Recalculate frame size for the actual file params
                frames_per_chunk = (framerate * FRAME_MS) // 1000
                chunk_bytes      = frames_per_chunk * n_channels * sampwidth
                sleep_time       = FRAME_MS / 1000.0

                _log(f"Streaming '{wav_path}' @ {framerate}Hz, {n_channels}ch")

                while not self._stop_event.is_set():
                    # Handle pause
                    while self._is_paused and not self._stop_event.is_set():
                        time.sleep(0.1)

                    data = wf.readframes(frames_per_chunk)
                    if not data:
                        break   # End of file

                    self._push_audio_frame(data)
                    time.sleep(sleep_time)

        except wave.Error as exc:
            _log(f"WAV read error: {exc}")
        except FileNotFoundError:
            _log(f"WAV file missing: {wav_path}")

    def _playback_worker(self, wav_path: str, title: str, requested_by: str):
        """Thread target: streams wav then fires on_song_end callback."""
        self._is_playing = True
        self._current_title  = title
        self._current_req_by = requested_by

        try:
            self._stream_wav(wav_path)
        finally:
            self._is_playing = False
            if not self._stop_event.is_set():
                _log(f"Song finished: {title}")
                if callable(self.on_song_end):
                    try:
                        self.on_song_end(title, requested_by)
                    except Exception as exc:
                        _log(f"on_song_end callback error: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(self, query: str, requested_by: str = "Auto DJ") -> bool:
        """
        Download (or load from cache) and stream the song.
        Returns True if playback started successfully.
        """
        # Stop any current playback first
        self.stop()

        wav_path = self._download_audio(query)
        if not wav_path:
            _log(f"Could not obtain audio for: {query}")
            return False

        self._stop_event.clear()
        self._is_paused = False

        # Derive a human-readable title from the query
        title = os.path.basename(query) if query.startswith("http") else query

        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            args=(wav_path, title, requested_by),
            daemon=True,
            name="playback-worker",
        )
        self._playback_thread.start()
        _log(f"Now playing: '{title}' (requested by {requested_by})")
        return True

    def pause(self):
        if self._is_playing:
            self._is_paused = True
            _log("Playback paused.")

    def resume(self):
        if self._is_playing and self._is_paused:
            self._is_paused = False
            _log("Playback resumed.")

    def stop(self):
        if self._is_playing or (self._playback_thread and self._playback_thread.is_alive()):
            self._stop_event.set()
            self._is_paused = False
            if self._playback_thread:
                self._playback_thread.join(timeout=3)
            self._is_playing = False
            _log("Playback stopped.")

    def skip(self):
        """Alias for stop(); queue_manager will start the next song."""
        _log("Song skipped.")
        self.stop()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def now_playing(self) -> dict:
        return {
            "title":        self._current_title,
            "requested_by": self._current_req_by,
            "is_playing":   self._is_playing,
            "is_paused":    self._is_paused,
        }