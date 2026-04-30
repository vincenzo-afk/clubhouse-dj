"""
queue_manager.py — FIFO song queue with auto-DJ fallback from default_songs.txt.
"""

import os
import random
import threading
from collections import deque
from datetime import datetime


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [QUEUE] {msg}")


class QueueManager:
    """
    Manages the song queue and coordinates with AudioPlayer and Announcer.

    Flow:
      add_song()   → enqueue → if nothing playing, start immediately
      on_song_end  → pull next from queue → if empty, auto-DJ from defaults
    """

    def __init__(self, config: dict, audio_player=None, announcer=None):
        self.config       = config
        self.audio_player = audio_player
        self.announcer    = announcer

        self.max_size       = config.get("max_queue_size", 20)
        self.default_songs_path = "./playlist/default_songs.txt"

        self._queue: deque = deque()
        self._now_playing: dict | None = None
        self._auto_dj_active = config.get("auto_dj_mode", True)
        self._lock = threading.Lock()

        # Wire audio player callback
        if self.audio_player:
            self.audio_player.on_song_end = self._on_song_end

        _log("QueueManager initialised.")

    # ------------------------------------------------------------------
    # Default songs
    # ------------------------------------------------------------------

    def _load_defaults(self) -> list[str]:
        """Load queries from default_songs.txt, return as list."""
        songs = []
        try:
            with open(self.default_songs_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        songs.append(line)
        except FileNotFoundError:
            _log("default_songs.txt not found — using fallback genre query.")
            genre = self.config.get("default_genre", "lofi chill")
            songs = [f"{genre} music"]
        return songs

    def _random_default(self) -> str:
        songs = self._load_defaults()
        if not songs:
            return self.config.get("default_genre", "lofi chill")
        return random.choice(songs)

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------

    def add_song(self, query: str, requested_by: str = "Auto DJ") -> str:
        """
        Enqueue a song.  Returns a status string for the user.
        If nothing is currently playing, starts playback immediately.
        """
        with self._lock:
            if len(self._queue) >= self.max_size:
                _log(f"Queue full ({self.max_size}). Rejected: {query}")
                return f"Queue is full ({self.max_size} songs). Try again later."

            self._queue.append({"query": query, "requested_by": requested_by})
            pos = len(self._queue)
            _log(f"Enqueued [{pos}]: '{query}' by {requested_by}")

        # Start immediately if nothing playing
        if not self.audio_player.is_playing:
            self._play_next()

        return f"Added to queue at position {pos}: {query}"

    def skip(self) -> str:
        """Skip the current song; play the next one."""
        if self.audio_player.is_playing:
            _log("Skip requested.")
            self.audio_player.skip()  # triggers _on_song_end via callback
            return "Skipping current song."
        return "Nothing is playing right now."

    def get_queue(self) -> list[dict]:
        """Return a copy of the current queue."""
        with self._lock:
            return list(self._queue)

    def get_now_playing(self) -> dict | None:
        return self._now_playing

    def clear_queue(self) -> str:
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
        _log(f"Queue cleared ({count} songs removed).")
        return f"Queue cleared. {count} songs removed."

    # ------------------------------------------------------------------
    # Auto DJ
    # ------------------------------------------------------------------

    def trigger_auto_dj(self):
        """Called by silence detector / scheduler when silence threshold hit."""
        if not self._auto_dj_active:
            _log("Auto DJ is disabled.")
            return

        if self.audio_player.is_playing:
            _log("Auto DJ triggered but audio is already playing.")
            return

        silence_minutes = self.config.get("silence_threshold_minutes", 10)
        _log(f"Auto DJ activated after {silence_minutes} minutes of silence.")

        if self.announcer:
            self.announcer.auto_dj_activated(silence_minutes)

        self._play_next(force_default=True)

    def enable_auto_dj(self):
        self._auto_dj_active = True
        _log("Auto DJ enabled.")

    def disable_auto_dj(self):
        self._auto_dj_active = False
        _log("Auto DJ disabled.")

    # ------------------------------------------------------------------
    # Internal playback control
    # ------------------------------------------------------------------

    def _play_next(self, force_default: bool = False):
        """
        Pull the next song from the queue.
        If the queue is empty, play a random default (if auto_dj active or forced).
        """
        entry = None
        with self._lock:
            if self._queue:
                entry = self._queue.popleft()

        if entry is None:
            if force_default or self._auto_dj_active:
                query = self._random_default()
                entry = {"query": query, "requested_by": "Auto DJ"}
                _log(f"Queue empty — Auto DJ selected: '{query}'")
                if self.announcer:
                    try:
                        self.announcer.queue_empty()
                    except Exception:
                        pass
            else:
                _log("Queue empty and Auto DJ is off. Waiting.")
                self._now_playing = None
                return

        self._now_playing = entry

        # Announce before playing
        if self.announcer and self.config.get("announce_songs", True):
            try:
                self.announcer.now_playing(
                    entry["query"], entry["requested_by"]
                )
            except Exception as exc:
                _log(f"Announce error: {exc}")

        # Start playback
        if self.audio_player:
            success = self.audio_player.play(
                entry["query"], entry["requested_by"]
            )
            if not success:
                _log(f"Playback failed for '{entry['query']}'. Moving to next.")
                self._play_next()  # try next song

    def _on_song_end(self, title: str, requested_by: str):
        """Callback fired by AudioPlayer when a song finishes naturally."""
        _log(f"Song ended: '{title}' — pulling next from queue.")
        self._play_next()