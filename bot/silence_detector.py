"""
silence_detector.py — Monitors Agora audio input frames, computes RMS energy,
and triggers Auto DJ when silence exceeds the configured threshold.
"""

import time
import threading
import struct
import numpy as np
from datetime import datetime


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [SILENCE] {msg}")


class SilenceDetector:
    """
    Monitors room audio.

    Usage:
        detector = SilenceDetector(config, on_silence_callback)
        detector.start_monitoring()
        # ... feed frames via: detector.feed_frame(pcm_bytes)
        detector.stop_monitoring()
    """

    # RMS values below this are considered silence
    RMS_SILENCE_THRESHOLD = 100   # out of 32768 for int16

    def __init__(self, config: dict, on_silence=None):
        self.config       = config
        self.on_silence   = on_silence   # callable()

        self.threshold_seconds = (
            config.get("silence_threshold_minutes", 10) * 60
        )
        self.sample_rate  = config.get("audio_sample_rate", 16000)
        self.channels     = config.get("audio_channels", 1)

        self._running         = False
        self._monitor_thread  = None
        self._lock            = threading.Lock()

        # RMS accumulator
        self._rms_window: list[float] = []
        self._window_size = 5   # rolling average over last N samples

        # Silence tracking
        self._silence_start: float | None = None
        self._silence_triggered           = False

        _log(f"SilenceDetector initialised. Threshold: {self.threshold_seconds}s")

    # ------------------------------------------------------------------
    # Feed frames from Agora callback
    # ------------------------------------------------------------------

    def feed_frame(self, pcm_bytes: bytes):
        """
        Call this from the Agora audio-receive callback.
        Computes RMS and updates the silence timer.
        """
        if not self._running:
            return

        rms = self._compute_rms(pcm_bytes)

        with self._lock:
            self._rms_window.append(rms)
            if len(self._rms_window) > self._window_size:
                self._rms_window.pop(0)

            avg_rms = sum(self._rms_window) / len(self._rms_window)

            if avg_rms < self.RMS_SILENCE_THRESHOLD:
                if self._silence_start is None:
                    self._silence_start = time.time()
                    _log(f"Silence started (RMS={avg_rms:.1f}).")
            else:
                # Audio activity detected — reset
                if self._silence_start is not None:
                    _log(f"Audio activity detected — silence timer reset (RMS={avg_rms:.1f}).")
                self._silence_start     = None
                self._silence_triggered = False

    # ------------------------------------------------------------------
    # Monitor thread
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        """
        Runs in a background thread.
        Checks if silence has exceeded the threshold every second.
        """
        _log("Monitor loop started.")
        while self._running:
            time.sleep(1)
            with self._lock:
                if self._silence_start is None:
                    continue
                elapsed = time.time() - self._silence_start
                if elapsed >= self.threshold_seconds and not self._silence_triggered:
                    self._silence_triggered = True
                    mins = int(elapsed // 60)
                    _log(f"Silence threshold exceeded ({mins} min). Triggering Auto DJ.")
                    if callable(self.on_silence):
                        try:
                            self.on_silence()
                        except Exception as exc:
                            _log(f"on_silence callback error: {exc}")

        _log("Monitor loop stopped.")

    # ------------------------------------------------------------------
    # Simulated monitoring (when Agora input is not available)
    # ------------------------------------------------------------------

    def _simulated_monitor_loop(self):
        """
        Fallback monitor: simulates silence by incrementing a timer
        without real Agora feed. Useful for testing without Agora.
        """
        _log("Simulated monitor loop started (no live Agora feed).")
        silence_start = time.time()
        while self._running:
            time.sleep(1)
            elapsed = time.time() - silence_start
            if elapsed >= self.threshold_seconds:
                _log(f"[Simulated] Silence threshold hit ({self.threshold_seconds}s).")
                silence_start = time.time()   # reset
                if callable(self.on_silence):
                    try:
                        self.on_silence()
                    except Exception as exc:
                        _log(f"on_silence callback error: {exc}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_monitoring(self, simulated: bool = False):
        if self._running:
            _log("Already monitoring.")
            return
        self._running = True
        self._silence_start     = None
        self._silence_triggered = False

        target = self._simulated_monitor_loop if simulated else self._monitor_loop
        self._monitor_thread = threading.Thread(
            target=target,
            daemon=True,
            name="silence-monitor",
        )
        self._monitor_thread.start()
        _log("Silence monitoring started.")

    def stop_monitoring(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        _log("Silence monitoring stopped.")

    def reset_timer(self):
        """Call this whenever audio activity is externally detected (e.g. song starts)."""
        with self._lock:
            self._silence_start     = None
            self._silence_triggered = False
        _log("Silence timer manually reset.")

    def is_silent(self) -> bool:
        with self._lock:
            return self._silence_start is not None

    def update_threshold(self, minutes: int):
        """Update silence threshold dynamically."""
        minutes = max(5, min(60, minutes))
        self.threshold_seconds = minutes * 60
        _log(f"Silence threshold updated to {minutes} minutes.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rms(pcm_bytes: bytes) -> float:
        """Compute Root Mean Square of a PCM int16 byte buffer."""
        if not pcm_bytes:
            return 0.0
        try:
            num_samples = len(pcm_bytes) // 2
            samples = np.frombuffer(pcm_bytes[:num_samples * 2], dtype=np.int16).astype(np.float32)
            if len(samples) == 0:
                return 0.0
            rms = float(np.sqrt(np.mean(samples ** 2)))
            return rms
        except Exception:
            return 0.0