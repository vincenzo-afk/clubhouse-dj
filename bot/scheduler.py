"""
scheduler.py — APScheduler-based countdown that fires trigger_auto_dj()
after the configured silence threshold. Works alongside SilenceDetector.
"""

import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [SCHEDULER] {msg}")


class Scheduler:
    """
    Maintains a countdown timer for silence detection.

    When reset_timer() isn't called within `threshold_minutes` minutes,
    the _fire() callback triggers Auto DJ.

    This complements SilenceDetector: SilenceDetector tracks RMS from frames,
    while Scheduler provides a coarse wall-clock fallback (e.g. when nobody
    is speaking AND no music is playing but we have no frame feed).
    """

    def __init__(self, config: dict, queue_manager=None):
        self.config        = config
        self.queue_manager = queue_manager

        self._threshold_minutes = config.get("silence_threshold_minutes", 10)
        self._threshold_seconds = self._threshold_minutes * 60

        self._scheduler   = BackgroundScheduler(daemon=True)
        self._last_reset  = datetime.now().timestamp()
        self._active      = False
        self._lock        = threading.Lock()
        self._fired_flag  = False   # prevent double-trigger per cycle

        _log(f"Scheduler initialised. Threshold: {self._threshold_minutes} min.")

    # ------------------------------------------------------------------
    # Scheduler lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the background scheduler (check every 10 seconds)."""
        if self._active:
            _log("Already running.")
            return
        self._active = True
        self._last_reset = datetime.now().timestamp()
        self._fired_flag = False

        self._scheduler.add_job(
            self._check_silence,
            trigger=IntervalTrigger(seconds=10),
            id="silence_check",
            replace_existing=True,
        )
        try:
            self._scheduler.start()
            _log("Scheduler started.")
        except Exception as exc:
            _log(f"Scheduler start error: {exc}")

    def stop(self):
        if not self._active:
            return
        self._active = False
        try:
            self._scheduler.shutdown(wait=False)
            _log("Scheduler stopped.")
        except Exception as exc:
            _log(f"Scheduler stop error: {exc}")

    # ------------------------------------------------------------------
    # Timer control
    # ------------------------------------------------------------------

    def reset_timer(self):
        """
        Call whenever audio activity is detected (music started, user spoke).
        Resets the countdown.
        """
        with self._lock:
            self._last_reset = datetime.now().timestamp()
            self._fired_flag = False

    def set_threshold(self, minutes: int):
        """Dynamically update the silence threshold (5–60 min)."""
        minutes = max(5, min(60, minutes))
        with self._lock:
            self._threshold_minutes = minutes
            self._threshold_seconds = minutes * 60
            self._fired_flag = False
        _log(f"Threshold updated to {minutes} minutes.")

    def get_threshold_minutes(self) -> int:
        return self._threshold_minutes

    # ------------------------------------------------------------------
    # Internal check
    # ------------------------------------------------------------------

    def _check_silence(self):
        """Periodic job: fire if threshold exceeded and not already triggered."""
        with self._lock:
            elapsed = datetime.now().timestamp() - self._last_reset
            if elapsed >= self._threshold_seconds and not self._fired_flag:
                self._fired_flag = True
                mins = int(elapsed // 60)
                _log(f"Silence timer fired after {mins} min. Triggering Auto DJ.")
                self._trigger_auto_dj()

    def _trigger_auto_dj(self):
        if self.queue_manager:
            try:
                self.queue_manager.trigger_auto_dj()
            except Exception as exc:
                _log(f"Auto DJ trigger error: {exc}")
        else:
            _log("No QueueManager attached — cannot trigger Auto DJ.")