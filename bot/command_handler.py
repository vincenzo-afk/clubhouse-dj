"""
command_handler.py — Parses Clubhouse chat messages and dispatches
to the appropriate bot module. Manages skip votes and mod privileges.
"""

import threading
from datetime import datetime


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CMD] {msg}")


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------
HELP_TEXT = """
ClubDJ Commands:
  !play <song/URL>  — Add song to queue
  !skip             — Vote to skip (3 votes needed, instant for mods)
  !queue            — Show current queue
  !np               — Announce now playing
  !timer <minutes>  — Set silence threshold (5–60 min)
  !stop             — Stop Auto DJ
  !start            — Resume Auto DJ
  !clear            — Clear the queue
  !help             — Show this message
""".strip()


class CommandHandler:
    """
    Handles chat commands.

    Wire it up by calling:
        handler.handle_message(username, message, is_moderator)
    """

    def __init__(
        self,
        config: dict,
        queue_manager=None,
        announcer=None,
        scheduler=None,
        silence_detector=None,
        send_chat_fn=None,   # callable(message_str) to post text to room
    ):
        self.config           = config
        self.queue_manager    = queue_manager
        self.announcer        = announcer
        self.scheduler        = scheduler
        self.silence_detector = silence_detector
        self.send_chat        = send_chat_fn or (lambda m: _log(f"[CHAT OUT] {m}"))

        self.votes_required   = config.get("skip_votes_required", 3)
        self.bot_name         = config.get("bot_name", "ClubDJ 🎧")

        self._skip_votes: set = set()   # usernames who voted skip
        self._skip_lock = threading.Lock()

        _log("CommandHandler initialised.")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle_message(self, username: str, message: str, is_moderator: bool = False):
        """
        Route an incoming chat message to the correct handler.
        `username`    — display name of the sender
        `message`     — raw chat string
        `is_moderator`— True if sender is a room moderator
        """
        raw = message.strip()
        if not raw.startswith("!"):
            return   # Not a command

        parts    = raw.split(maxsplit=1)
        command  = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""

        _log(f"Command from {username} {'[MOD]' if is_moderator else ''}: {raw}")

        handlers = {
            "!play":   self._cmd_play,
            "!skip":   self._cmd_skip,
            "!queue":  self._cmd_queue,
            "!np":     self._cmd_np,
            "!timer":  self._cmd_timer,
            "!stop":   self._cmd_stop,
            "!start":  self._cmd_start,
            "!clear":  self._cmd_clear,
            "!help":   self._cmd_help,
        }

        fn = handlers.get(command)
        if fn:
            try:
                fn(username=username, argument=argument, is_mod=is_moderator)
            except Exception as exc:
                _log(f"Error in handler '{command}': {exc}")
                self.send_chat(f"⚠️ Error processing command: {exc}")
        else:
            self.send_chat(f"Unknown command: {command}. Type !help for a list.")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_play(self, username: str, argument: str, is_mod: bool):
        if not argument:
            self.send_chat("Usage: !play <song name or YouTube URL>")
            return
        if not self.queue_manager:
            self.send_chat("Queue manager not available.")
            return
        result = self.queue_manager.add_song(argument, requested_by=username)
        self.send_chat(f"🎵 {result}")

    def _cmd_skip(self, username: str, argument: str, is_mod: bool):
        if not self.queue_manager:
            self.send_chat("Queue manager not available.")
            return

        if is_mod:
            result = self.queue_manager.skip()
            self.send_chat(f"⏭️ [MOD] {result}")
            self._reset_skip_votes()
            return

        with self._skip_lock:
            self._skip_votes.add(username)
            count = len(self._skip_votes)

        self.send_chat(
            f"⏭️ Skip vote by {username}: {count}/{self.votes_required}."
        )

        if count >= self.votes_required:
            result = self.queue_manager.skip()
            self.send_chat(f"⏭️ Vote passed! {result}")
            self._reset_skip_votes()

    def _cmd_queue(self, username: str, argument: str, is_mod: bool):
        if not self.queue_manager:
            self.send_chat("Queue manager not available.")
            return
        q = self.queue_manager.get_queue()
        if not q:
            self.send_chat("📋 Queue is empty. Use !play to add songs.")
            return

        lines = [f"📋 Queue ({len(q)} songs):"]
        for i, entry in enumerate(q, 1):
            lines.append(f"  {i}. {entry['query']} — {entry['requested_by']}")
        self.send_chat("\n".join(lines))

        # Also announce via TTS
        if self.announcer:
            tts_text = f"There are {len(q)} songs in the queue."
            self.announcer.announce(tts_text, blocking=False)

    def _cmd_np(self, username: str, argument: str, is_mod: bool):
        if not self.queue_manager:
            self.send_chat("Queue manager not available.")
            return
        np = self.queue_manager.get_now_playing()
        if not np:
            self.send_chat("🎧 Nothing is playing right now.")
            return
        text = f"🎧 Now playing: {np['query']} (requested by {np['requested_by']})"
        self.send_chat(text)
        if self.announcer:
            self.announcer.now_playing(np["query"], np["requested_by"])

    def _cmd_timer(self, username: str, argument: str, is_mod: bool):
        if not is_mod:
            self.send_chat("⚠️ Only moderators can change the silence timer.")
            return
        try:
            minutes = int(argument)
        except ValueError:
            self.send_chat("Usage: !timer <minutes> (5–60)")
            return

        minutes = max(5, min(60, minutes))

        if self.scheduler:
            self.scheduler.set_threshold(minutes)
        if self.silence_detector:
            self.silence_detector.update_threshold(minutes)

        self.send_chat(f"⏱️ Silence threshold set to {minutes} minutes.")

    def _cmd_stop(self, username: str, argument: str, is_mod: bool):
        if not is_mod:
            self.send_chat("⚠️ Only moderators can stop Auto DJ.")
            return
        if self.queue_manager:
            self.queue_manager.disable_auto_dj()
        if self.queue_manager and self.queue_manager.audio_player:
            self.queue_manager.audio_player.stop()
        if self.scheduler:
            self.scheduler.stop()
        self.send_chat("⏹️ Auto DJ stopped.")

    def _cmd_start(self, username: str, argument: str, is_mod: bool):
        if not is_mod:
            self.send_chat("⚠️ Only moderators can start Auto DJ.")
            return
        if self.queue_manager:
            self.queue_manager.enable_auto_dj()
        if self.scheduler:
            self.scheduler.start()
        self.send_chat("▶️ Auto DJ resumed.")

    def _cmd_clear(self, username: str, argument: str, is_mod: bool):
        if not is_mod:
            self.send_chat("⚠️ Only moderators can clear the queue.")
            return
        if self.queue_manager:
            result = self.queue_manager.clear_queue()
            self.send_chat(f"🗑️ {result}")
        else:
            self.send_chat("Queue manager not available.")

    def _cmd_help(self, username: str, argument: str, is_mod: bool):
        self.send_chat(HELP_TEXT)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reset_skip_votes(self):
        with self._skip_lock:
            self._skip_votes.clear()

    def reset_skip_votes_for_new_song(self):
        """Call this from QueueManager when a new song starts."""
        self._reset_skip_votes()
        _log("Skip votes reset for new song.")