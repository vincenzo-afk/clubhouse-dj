"""
clubhouse_client.py — Real Clubhouse API integration.

Wires the bot into the official Clubhouse web API (via the `clubhouse-py`
package) for authentication, joining rooms, speaker control and chat,
and uses PubNub (Clubhouse's real-time event bus) to receive in-room chat
messages that are dispatched to the command handler.

Clubhouse audio rooms run on Agora RTC. The join_channel response returns an
`agora_channel`, a random `agora_token`, and `rtc_token`/`pubnub` metadata so
a client can both speak into the room and listen to room events (chat,
user join/leave, speaker updates).
"""

import json
import logging
import threading
import time
from datetime import datetime

import requests

try:
    from clubhouse.clubhouse import Clubhouse
    CLUBHOUSE_PY_AVAILABLE = True
except ImportError:
    CLUBHOUSE_PY_AVAILABLE = False

try:
    import pubnub as _pn  # noqa: F401
    from pubnub.callbacks import SubscribeCallback
    from pubnub.enums import PNStatusCategory
    from pubnub.pnconfiguration import PNConfiguration
    from pubnub.pubnub import PubNub
    PUBNUB_AVAILABLE = True
except ImportError:
    PUBNUB_AVAILABLE = False

logger = logging.getLogger(__name__)


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [CLUBHOUSE] {msg}")


class ClubhouseClient:
    """
    Handles the full lifecycle:
      login(token) -> join_room(channel) -> (pubnub chat events, agora room)
    """

    def __init__(self, credentials: dict, on_message=None):
        """
        credentials: dict with keys:
            - user_id, user_token, device_id  (obtained once via phone auth)
            - phone_number                  (only needed for first-time auth)
        on_message: callback(username: str, message: str, is_moderator: bool)
        """
        self.credentials = credentials
        self.on_message = on_message

        self.room_id = None
        self.channel = None
        self.channel_id = None
        self.agora_channel = None
        self.agora_token = None
        self.agora_uid = None
        self.is_speaker = False
        self.is_moderator = False
        self.my_user_id = None

        self._client = None
        self._pn = None
        self._keepalive_thread = None
        self._running = False

        _log("ClubhouseClient initialized.")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    @staticmethod
    def check_for_update() -> dict:
        """Lightweight API health-check (no auth needed)."""
        ch = Clubhouse()
        return ch.check_for_update()

    def login(self, user_id: str, user_token: str, device_id: str):
        """Authenticate the client with a previously obtained auth token."""
        self._client = Clubhouse(
            user_id=user_id,
            user_token=user_token,
            user_device=device_id,
        )
        self.credentials["user_id"] = user_id
        self.credentials["user_token"] = user_token
        self.credentials["device_id"] = device_id

        # Verify the token actually works
        try:
            me = self._client.me()
            if me.get("success"):
                self.my_user_id = me["user_profile"].get("user_id")
                self.user_name = me["user_profile"].get("name", "ClubDJ")
                _log(f"Authenticated as {self.user_name} (uid={self.my_user_id}).")
            else:
                _log(f"Auth token rejected by API: {me}")
        except Exception as exc:
            _log(f"Auth verification error: {exc}")
            raise

    # ------------------------------------------------------------------
    # Room lifecycle
    # ------------------------------------------------------------------

    def join_room(self, channel: str):
        """
        Join a Clubhouse room (channel).  Populates agora_* fields used by
        the AudioPlayer to stream music into the room.
        """
        if not self._client:
            raise RuntimeError("Not authenticated. Call login() first.")

        resp = self._client.join_channel(channel)
        if not resp.get("success"):
            _log(f"join_channel failed: {resp}")
            raise RuntimeError(f"Failed to join channel {channel}: {resp}")

        channel_info = resp.get("channel", {})
        self.channel = channel
        self.channel_id = channel_info.get("channel_id")
        self.room_id = channel

        self.is_speaker = channel_info.get("is_speaker", False)
        self.is_moderator = channel_info.get("is_moderator", False)
        self.agora_channel = channel_info.get("agora_channel")
        self.agora_token = channel_info.get("randomized_agora_token") or channel_info.get("rtc_token")
        self.agora_uid = channel_info.get("agora_uid")

        _log(
            f"Joined room '{channel}' (channel_id={self.channel_id}). "
            f"speaker={self.is_speaker} mod={self.is_moderator} "
            f"agora_channel={self.agora_channel}"
        )

        # Start PubNub chat subscription in the background
        pubnub_info = channel_info.get("pubnub", {})
        if PUBNUB_AVAILABLE and pubnub_info:
            self._start_pubnub(
                token=pubnub_info.get("access_token"),
                origin=pubnub_info.get("origin", "https://clubhouse.pubnubapi.com"),
            )
        else:
            _log("PubNub unavailable — chat commands will not be received.")

        # Start keep-alive pings (Clubhouse kicks idle clients)
        self._running = True
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="ch-keepalive"
        )
        self._keepalive_thread.start()

        return True

    def leave_room(self):
        if self._running:
            self._running = False
        if self._pn:
            try:
                self._pn.unsubscribe_all()
                self._pn.stop()
            except Exception as exc:
                _log(f"PubNub shutdown error: {exc}")
            self._pn = None

        if self._client and self.channel:
            try:
                self._client.leave_channel(self.channel)
                _log(f"Left room: {self.channel}")
            except Exception as exc:
                _log(f"leave_channel error: {exc}")
        self.room_id = None
        self.channel = None
        return True

    def send_chat(self, message: str):
        """Post a chat message to the room via PubNub (like the official app)."""
        if not self._pn or not self.room_id:
            _log(f"[CHAT OUT] {message}")
            return False
        try:
            # Clubhouse publishes chat as a pubnub message with user metadata
            from pubnub.models.consumer.pubsub import PNPublishResult
            result: PNPublishResult = self._pn.publish().channel(
                self.room_id
            ).message({
                "body": message,
                "user_id": int(self.my_user_id) if self.my_user_id else 0,
                "user_is_speaker": self.is_speaker,
                "name": getattr(self, "user_name", "ClubDJ"),
                "user_id_to_display_as_following": [],
            }).sync()
            _log(f"[CHAT OUT] {message}")
            return True
        except Exception as exc:
            _log(f"Chat publish error: {exc}")
            return False

    # ------------------------------------------------------------------
    # Speaker / moderator helpers
    # ------------------------------------------------------------------

    def raise_hand(self, up: bool = True):
        if self._client and self.channel:
            resp = self._client.audience_reply(
                self.channel, raise_hands=up, unraise_hands=not up
            )
            if resp.get("success"):
                _log(f"Raise hand {'up' if up else 'down'}.")
            else:
                _log(f"Raise hand failed: {resp}")

    def active_ping(self):
        """Keep-alive ping so the server keeps us in the room."""
        if self._client and self.channel:
            try:
                self._client.active_ping(self.channel)
            except Exception as exc:
                _log(f"active_ping error: {exc}")

    # ------------------------------------------------------------------
    # PubNub chat subscription
    # ------------------------------------------------------------------

    def _start_pubnub(self, token: str, origin: str):
        if not token:
            _log("No pubnub access token — chat will be offline.")
            return
        try:
            pnconfig = PNConfiguration()
            pnconfig.publish_key = Clubhouse.PUBNUB_PUB_KEY
            pnconfig.subscribe_key = Clubhouse.PUBNUB_SUB_KEY
            pnconfig.auth_key = token
            pnconfig.user_id = str(self.my_user_id or 0)
            pnconfig.ssl = True

            self._pn = PubNub(pnconfig)
            self._pn.add_listener(_ChatListener(self))
            self._pn.subscribe().channels([self.room_id]).execute()
            _log(f"Subscribed to PubNub channel '{self.room_id}' for chat.")
        except Exception as exc:
            _log(f"PubNub subscription error: {exc}")

    def _on_message(self, username: str, message: str, is_moderator: bool):
        if callable(self.on_message):
            try:
                self.on_message(username, message, is_moderator)
            except Exception as exc:
                _log(f"on_message callback error: {exc}")

    def _keepalive_loop(self):
        """Ping every 30s while in a room (mirrors the official app)."""
        interval = 30
        while self._running:
            self.active_ping()
            time.sleep(interval)
        _log("Keepalive loop stopped.")


class _ChatListener(SubscribeCallback):
    """Extracts chat messages from PubNub events for the bot."""

    def __init__(self, client: ClubhouseClient):
        super().__init__()
        self.client = client

    def message(self, pubnub, message):
        try:
            data = message.message
            if not isinstance(data, dict):
                return
            body = data.get("body")
            if not body:
                return
            sender_id = data.get("user_id") or (data.get("user") or {}).get("user_id")
            username = (data.get("name") or data.get("user") or {}).get(
                "name", str(sender_id or "?")
            )
            is_moderator = bool(data.get("user_is_moderator", False))
            self.client._on_message(username, body, is_moderator)
        except Exception as exc:
            logger.error(f"Chat parsing error: {exc}", exc_info=True)

    def status(self, pubnub, status):
        if status.category == PNStatusCategory.PNConnectedCategory:
            _log("PubNub connection established.")
        elif status.category == PNStatusCategory.PNDisconnectedCategory:
            _log("PubNub disconnected.")
