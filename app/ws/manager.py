from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Tracks live WebSocket connections and per-user metadata."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._user_data: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(
        self,
        uid: str,
        websocket: WebSocket,
        display_name: str,
        email: str,
        photo_url: str,
    ) -> None:
        """Register a new authenticated connection."""
        self._connections[uid] = websocket
        self._user_data[uid] = {
            "displayName": display_name,  # from Firebase JWT (Google account name)
            "nickName": "",               # custom nick set via profile_update (empty = use displayName)
            "email": email,
            "photoURL": photo_url,
            "status": "online",
            "mood": "",
        }

    def disconnect(self, uid: str) -> None:
        """Remove a connection.  Silent no-op when *uid* is unknown."""
        self._connections.pop(uid, None)
        self._user_data.pop(uid, None)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_to(self, uid: str, payload: dict[str, Any]) -> None:
        """Send *payload* to a single connected user.  No-op if not connected."""
        ws = self._connections.get(uid)
        if ws is not None:
            await ws.send_text(json.dumps(payload))

    async def broadcast_to(self, uids: list[str], payload: dict[str, Any]) -> None:
        """Send *payload* to every uid in *uids* that is currently connected."""
        for uid in uids:
            await self.send_to(uid, payload)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_connected_uids(self) -> list[str]:
        return list(self._connections.keys())

    def get_user_data(self, uid: str) -> dict[str, Any] | None:
        return self._user_data.get(uid)

    def update_user_data(self, uid: str, **kwargs: Any) -> None:
        """Merge *kwargs* into the stored data for *uid*.  No-op if unknown."""
        if uid in self._user_data:
            self._user_data[uid].update(kwargs)

    def connected_count(self) -> int:
        return len(self._connections)


# Module-level singleton used by the rest of the application.
manager = ConnectionManager()


# ------------------------------------------------------------------
# Inline self-tests
# ------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import sys
    from unittest.mock import AsyncMock

    async def run_tests() -> None:
        m = ConnectionManager()

        # --- connect adds entries ---
        ws1 = AsyncMock()
        ws1.send_text = AsyncMock()
        m.connect("uid1", ws1, "Alice", "alice@example.com", "https://example.com/alice.png")
        assert m.connected_count() == 1, "connect: count should be 1"
        assert m.get_user_data("uid1") is not None, "connect: user_data missing"
        assert m.get_user_data("uid1")["status"] == "online", "connect: default status"
        assert m.get_user_data("uid1")["mood"] == "", "connect: default mood"
        assert "uid1" in m.get_connected_uids(), "connect: uid missing from list"

        # --- second user ---
        ws2 = AsyncMock()
        ws2.send_text = AsyncMock()
        m.connect("uid2", ws2, "Bob", "bob@example.com", "")
        assert m.connected_count() == 2, "connect: count should be 2"

        # --- send_to reaches the socket ---
        await m.send_to("uid1", {"type": "ping"})
        ws1.send_text.assert_called_once()

        # --- send_to unknown uid is a no-op (no raise) ---
        await m.send_to("ghost", {"type": "ping"})  # must not raise

        # --- broadcast_to reaches multiple sockets ---
        ws1.send_text.reset_mock()
        ws2.send_text.reset_mock()
        await m.broadcast_to(["uid1", "uid2", "nobody"], {"type": "ping"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

        # --- update_user_data merges ---
        m.update_user_data("uid1", mood="feeling emo today", status="away")
        assert m.get_user_data("uid1")["mood"] == "feeling emo today"
        assert m.get_user_data("uid1")["status"] == "away"

        # --- update_user_data on unknown uid is silent ---
        m.update_user_data("ghost", mood="spooky")  # must not raise

        # --- disconnect removes entries ---
        m.disconnect("uid1")
        assert m.connected_count() == 1, "disconnect: count should be 1"
        assert m.get_user_data("uid1") is None, "disconnect: user_data still present"
        assert "uid1" not in m.get_connected_uids()

        # --- disconnect unknown uid is silent ---
        m.disconnect("nobody")  # must not raise

        print("All tests passed OK")

    asyncio.run(run_tests())
    sys.exit(0)
