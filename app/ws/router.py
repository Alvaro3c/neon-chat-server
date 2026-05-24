"""WebSocket endpoint — authentication handshake and message receive loop."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.auth import verify_id_token
from app.ws import schemas as ws_schemas
from app.ws.events import AuthErrorEvent, AuthOkEvent, ContactStatusEvent, ErrorEvent
from app.ws.handlers import handle_message, handle_reaction, handle_typing
from app.ws.manager import manager
from app.ws.presence import get_contact_uids

logger = logging.getLogger(__name__)

router = APIRouter()

_AUTH_TIMEOUT = 5  # seconds

# Accepted values for the ``status_update`` message type.
_VALID_STATUSES: frozenset[str] = frozenset({"online", "away", "busy", "offline"})

_MAX_MOOD = 140  # characters

# Schema lookup for incoming event validation (msg_type → Pydantic model).
# Unknown types are not in this map and are handled by the "else" branch.
_INCOMING_SCHEMAS: dict[str, type] = {
    "message":       ws_schemas.MessageEvent,
    "typing":        ws_schemas.TypingEvent,
    "reaction":      ws_schemas.ReactionEvent,
    "status_update": ws_schemas.StatusUpdateEvent,
    "mood_update":   ws_schemas.MoodUpdateEvent,
    "refresh_token": ws_schemas.RefreshTokenEvent,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _broadcast_presence(
    uid: str,
    status: str,
    mood: str,
) -> None:
    """Fetch active contacts for *uid*, filter to connected ones, broadcast.

    Sends a single ``contact_status`` event to every contact that is
    currently connected — no one outside that set is notified.
    """
    contact_uids = await get_contact_uids(uid)
    connected = set(manager.get_connected_uids())
    targets = [u for u in contact_uids if u in connected]
    event: ContactStatusEvent = {
        "type": "contact_status",
        "uid": uid,
        "status": status,
        "mood": mood,
    }
    await manager.broadcast_to(targets, event)
    logger.debug(
        "presence broadcast | uid=%s status=%s mood=%r → %d target(s)",
        uid,
        status,
        mood,
        len(targets),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Single WebSocket endpoint for all real-time traffic.

    Auth flow
    ---------
    1. Accept the raw connection.
    2. Wait up to ``_AUTH_TIMEOUT`` seconds for the first message; close 1008
       on timeout.
    3. Expect ``{"type": "auth", "token": "<firebase-id-token>"}``.
       Bad shape → send AuthErrorEvent and close.
    4. Verify the token with Firebase Admin SDK.
       Failure → send AuthErrorEvent and close.
       Success → register with ConnectionManager, send AuthOkEvent.
    5. Targeted on-connect presence:
       a. Broadcast ContactStatusEvent {status: "online"} to connected contacts
          that share an active conversation with this user.
       b. Send ContactStatusEvent for each of those contacts back to this user
          so they immediately see accurate presence dots.
    6. Enter receive loop.  Supported message types:
       ``message``, ``typing``, ``reaction``, ``status_update``, ``mood_update``.
    7. On any disconnect (clean or error): disconnect from manager, broadcast
       ContactStatusEvent {status: "offline"} to the same targeted set.
    """
    await websocket.accept()

    uid: str | None = None

    try:
        # ── 1. Wait for the auth message ──────────────────────────────────
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=_AUTH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("WS auth timeout after %ds — closing 1008", _AUTH_TIMEOUT)
            await websocket.close(code=1008)
            return

        # ── 2. Parse JSON ─────────────────────────────────────────────────
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            err: AuthErrorEvent = {"type": "auth_error", "message": "Invalid JSON"}
            await websocket.send_text(json.dumps(err))
            await websocket.close(code=1008)
            return

        # ── 3. Validate shape ─────────────────────────────────────────────
        if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            err = {
                "type": "auth_error",
                "message": "Expected {\"type\": \"auth\", \"token\": \"<id-token>\"}",
            }
            await websocket.send_text(json.dumps(err))
            await websocket.close(code=1008)
            return

        # ── 4. Verify Firebase ID token ───────────────────────────────────
        try:
            claims = await verify_id_token(msg["token"])
        except ValueError as exc:
            err = {"type": "auth_error", "message": str(exc)}
            await websocket.send_text(json.dumps(err))
            await websocket.close(code=1008)
            return

        uid = str(claims["uid"])
        display_name: str = claims.get("name") or ""
        email: str = claims.get("email") or ""
        photo_url: str = claims.get("picture") or ""

        # ── 5. Register and confirm ───────────────────────────────────────
        manager.connect(uid, websocket, display_name, email, photo_url)

        auth_ok: AuthOkEvent = {
            "type": "auth_ok",
            "uid": uid,
            "displayName": display_name,
            "email": email,
            "photoURL": photo_url,
        }
        await websocket.send_text(json.dumps(auth_ok))

        # ── 5a. Broadcast our "online" to connected contacts ──────────────
        contact_uids = await get_contact_uids(uid)
        connected_set = set(manager.get_connected_uids())
        connected_contacts = [u for u in contact_uids if u in connected_set]

        online_event: ContactStatusEvent = {
            "type": "contact_status",
            "uid": uid,
            "status": "online",
            "mood": "",
        }
        await manager.broadcast_to(connected_contacts, online_event)

        # ── 5b. Send each contact's current status back to us ────────────
        for contact_uid in connected_contacts:
            contact_data = manager.get_user_data(contact_uid)
            if contact_data is not None:
                back_event: ContactStatusEvent = {
                    "type": "contact_status",
                    "uid": contact_uid,
                    "status": contact_data.get("status", "online"),
                    "mood": contact_data.get("mood", ""),
                }
                await websocket.send_text(json.dumps(back_event))

        logger.info("User %s connected  (total: %d)", uid, manager.connected_count())

        # ── 6. Receive loop ───────────────────────────────────────────────
        while True:
            text = await websocket.receive_text()
            msg_type: str = ""  # initialise before the try so except can log it

            try:
                # ── JSON decode ───────────────────────────────────────────
                try:
                    payload: dict[str, Any] = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON from %s: %r", uid, text[:200])
                    continue

                msg_type = payload.get("type", "")
                logger.debug("Message from %s: type=%s", uid, msg_type)

                # ── Schema validation ─────────────────────────────────────
                schema_cls = _INCOMING_SCHEMAS.get(msg_type)
                if schema_cls is not None:
                    try:
                        schema_cls.model_validate(payload)
                    except ValidationError as exc:
                        logger.warning(
                            "Validation error from %s type=%r: %s",
                            uid, msg_type, exc,
                        )
                        invalid_err: ErrorEvent = {
                            "type": "error",
                            "code": "INVALID_PAYLOAD",
                            "message": str(exc),
                        }
                        await websocket.send_text(json.dumps(invalid_err))
                        continue

                # ── Dispatch ──────────────────────────────────────────────
                if msg_type == "message":
                    await handle_message(uid, payload)

                elif msg_type == "typing":
                    await handle_typing(uid, payload)

                elif msg_type == "reaction":
                    await handle_reaction(uid, payload)

                elif msg_type == "status_update":
                    await _handle_status_update(uid, websocket, payload)

                elif msg_type == "mood_update":
                    await _handle_mood_update(uid, websocket, payload)

                elif msg_type == "refresh_token":
                    await _handle_refresh_token(uid, websocket, payload)

                else:
                    logger.warning("Unhandled message type %r from %s", msg_type, uid)

            except Exception:
                logger.exception(
                    "Unexpected error in receive loop: uid=%s type=%r",
                    uid, msg_type,
                )
                server_err: ErrorEvent = {
                    "type": "error",
                    "code": "SERVER_ERROR",
                    "message": "An unexpected error occurred.",
                }
                try:
                    await websocket.send_text(json.dumps(server_err))
                except Exception:
                    pass  # socket may already be gone; don't cascade

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: uid=%s", uid)
    except Exception:
        logger.exception("Unexpected error in WS handler: uid=%s", uid)
    finally:
        if uid is not None:
            # Fetch contacts BEFORE disconnect so Firestore still resolves
            # them; filter against the manager AFTER disconnect so the
            # departing user is not in the connected set.
            contact_uids = await get_contact_uids(uid)
            manager.disconnect(uid)
            connected_after = set(manager.get_connected_uids())
            targets = [u for u in contact_uids if u in connected_after]

            offline_event: ContactStatusEvent = {
                "type": "contact_status",
                "uid": uid,
                "status": "offline",
                "mood": "",
            }
            await manager.broadcast_to(targets, offline_event)
            logger.info(
                "User %s went offline  (remaining: %d)", uid, manager.connected_count()
            )


# ---------------------------------------------------------------------------
# Presence sub-handlers (called from the receive loop)
# ---------------------------------------------------------------------------


async def _handle_status_update(
    uid: str,
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    """Handle ``{"type": "status_update", "status": str}``.

    Valid statuses: ``online``, ``away``, ``busy``, ``offline``.
    Persists the new status in the manager and broadcasts a
    ``contact_status`` event (carrying the user's current mood) to all
    connected contacts that share an active conversation.
    """
    status: Any = payload.get("status")

    if not isinstance(status, str) or status not in _VALID_STATUSES:
        error_event: ErrorEvent = {
            "type": "error",
            "code": "INVALID_STATUS",
            "message": (
                f"status must be one of: {', '.join(sorted(_VALID_STATUSES))}"
            ),
        }
        await websocket.send_text(json.dumps(error_event))
        return

    manager.update_user_data(uid, status=status)
    user_data = manager.get_user_data(uid) or {}
    current_mood: str = user_data.get("mood", "")

    await _broadcast_presence(uid, status=status, mood=current_mood)
    logger.info("status_update | uid=%s status=%s", uid, status)


async def _handle_mood_update(
    uid: str,
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    """Handle ``{"type": "mood_update", "mood": str}``.

    Mood must be a string of at most 140 characters.  Persists the new mood
    in the manager and broadcasts a ``contact_status`` event (carrying the
    user's current status) to all connected contacts that share an active
    conversation.
    """
    mood: Any = payload.get("mood")

    if not isinstance(mood, str):
        error_event: ErrorEvent = {
            "type": "error",
            "code": "INVALID_MOOD",
            "message": "mood must be a string.",
        }
        await websocket.send_text(json.dumps(error_event))
        return

    if len(mood) > _MAX_MOOD:
        error_event = {
            "type": "error",
            "code": "INVALID_MOOD",
            "message": f"mood must be at most {_MAX_MOOD} characters.",
        }
        await websocket.send_text(json.dumps(error_event))
        return

    manager.update_user_data(uid, mood=mood)
    user_data = manager.get_user_data(uid) or {}
    current_status: str = user_data.get("status", "online")

    await _broadcast_presence(uid, status=current_status, mood=mood)
    logger.info("mood_update | uid=%s mood=%r", uid, mood)


async def _handle_refresh_token(
    uid: str,
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    """Handle ``{"type": "refresh_token", "token": str}``.

    Verifies a new Firebase ID token for the already-authenticated
    connection.

    * **Success** — updates ``displayName`` / ``photoURL`` in the manager
      (email and uid are immutable once authenticated) and sends an
      ``AuthOkEvent`` so the client can confirm the refresh.
    * **Failure** — sends ``AuthErrorEvent`` and keeps the connection open;
      the client is expected to retry or re-authenticate.
    """
    token: str = payload["token"]  # non-empty str already guaranteed by schema

    try:
        claims = await verify_id_token(token)
    except Exception as exc:
        logger.warning("Token refresh failed | uid=%s reason=%s", uid, exc)
        auth_err: AuthErrorEvent = {
            "type": "auth_error",
            "message": str(exc),
        }
        await websocket.send_text(json.dumps(auth_err))
        return

    # Update mutable profile fields; uid / email are immutable.
    new_display_name: str = claims.get("name") or ""
    new_photo_url: str = claims.get("picture") or ""
    manager.update_user_data(uid, displayName=new_display_name, photoURL=new_photo_url)

    user_data = manager.get_user_data(uid) or {}
    auth_ok: AuthOkEvent = {
        "type": "auth_ok",
        "uid": uid,
        "displayName": user_data.get("displayName", ""),
        "email": user_data.get("email", ""),
        "photoURL": user_data.get("photoURL", ""),
    }
    await websocket.send_text(json.dumps(auth_ok))
    logger.info("Token refreshed | uid=%s", uid)
