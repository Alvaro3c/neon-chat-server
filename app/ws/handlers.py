"""WebSocket message-type handlers.

Each public coroutine in this module corresponds to one ``type`` value that
can arrive in the receive loop.  Handlers are responsible for their own
validation and for sending any error or success events back over the socket.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from app.db import db
from app.ws.events import ErrorEvent, MessageEvent, ReactionEvent, TypingEvent
from app.ws.manager import manager

logger = logging.getLogger(__name__)

_MAX_TEXT = 2_000  # characters
_MAX_EMOJI = 10    # characters


# ---------------------------------------------------------------------------
# handle_message
# ---------------------------------------------------------------------------

async def handle_message(sender_uid: str, payload: dict[str, Any]) -> None:
    """Handle ``{"type": "message", "conversationId": str, "text": str}``.

    Parameters
    ----------
    sender_uid:
        UID of the already-authenticated user who sent this payload.
    payload:
        The full parsed JSON dict from the WebSocket frame.

    Flow
    ----
    1. Validate *text* (non-empty, ≤ 2 000 chars) and *conversationId*.
    2. Fetch the conversation document from Firestore; verify sender is a
       participant and the conversation is active.
    3. Derive the other participant uid(s).
    4. Generate a UUID messageId and UTC ISO-8601 timestamp.
    5. Build a ``MessageEvent`` and deliver it to **all** participants
       (sender included — serves as delivery confirmation).
    """
    conversation_id: Any = payload.get("conversationId")
    text: Any = payload.get("text")

    # ── 1. Validate inputs ────────────────────────────────────────────────────

    if not isinstance(text, str) or not text.strip():
        await _send_error(
            sender_uid,
            code="INVALID_MESSAGE",
            message="text must be a non-empty string.",
        )
        return

    if len(text) > _MAX_TEXT:
        await _send_error(
            sender_uid,
            code="INVALID_MESSAGE",
            message=f"text exceeds the {_MAX_TEXT:,}-character limit.",
        )
        return

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        await _send_error(
            sender_uid,
            code="INVALID_MESSAGE",
            message="conversationId must be a non-empty string.",
        )
        return

    # ── 2. Firestore lookup ───────────────────────────────────────────────────

    try:
        doc_ref = db.collection("conversations").document(conversation_id)
        doc_snapshot = await asyncio.to_thread(doc_ref.get)
    except Exception:
        logger.exception("Firestore error fetching conversation %s", conversation_id)
        await _send_error(
            sender_uid,
            code="SERVER_ERROR",
            message="Could not fetch the conversation. Please try again.",
        )
        return

    if not doc_snapshot.exists:
        await _send_error(
            sender_uid,
            code="NOT_PARTICIPANT",
            message="Conversation not found or you are not a participant.",
        )
        return

    conv_data: dict[str, Any] = doc_snapshot.to_dict() or {}
    participants: list[str] = conv_data.get("participants", [])
    status: str = conv_data.get("status", "")

    if sender_uid not in participants or status != "active":
        await _send_error(
            sender_uid,
            code="NOT_PARTICIPANT",
            message="Conversation not found or you are not a participant.",
        )
        return

    # ── 3. Other participant(s) (kept for potential future multi-user use) ────

    # All recipients = every participant, sender included (delivery receipt).
    recipients: list[str] = participants

    # ── 4. Generate identifiers ───────────────────────────────────────────────

    message_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"

    # ── 5. Build the event ────────────────────────────────────────────────────

    user_data = manager.get_user_data(sender_uid)
    sender_name: str = (user_data or {}).get("displayName") or ""

    event: MessageEvent = {
        "type": "message",
        "conversationId": conversation_id,
        "messageId": message_id,
        "senderUid": sender_uid,
        "senderName": sender_name,
        "text": text,
        "timestamp": timestamp,
    }

    # ── 6. Deliver to all participants ────────────────────────────────────────

    for uid in recipients:
        await manager.send_to(uid, event)

    logger.info(
        "msg %s | conv=%s | from=%s | to=%d recipient(s)",
        message_id,
        conversation_id,
        sender_uid,
        len(recipients),
    )


# ---------------------------------------------------------------------------
# handle_typing
# ---------------------------------------------------------------------------

async def handle_typing(sender_uid: str, payload: dict[str, Any]) -> None:
    """Handle ``{"type": "typing", "conversationId": str}``.

    Parameters
    ----------
    sender_uid:
        UID of the already-authenticated user who sent this payload.
    payload:
        The full parsed JSON dict from the WebSocket frame.

    Flow
    ----
    1. Validate *conversationId*.
    2. Fetch the conversation from Firestore; silently drop if not found or
       sender is not a participant (typing is best-effort, no error reply).
    3. Find the other participant (uid ≠ sender).
    4. Send TypingEvent to the OTHER participant only.
    """
    conversation_id: Any = payload.get("conversationId")

    # ── 1. Validate conversationId ────────────────────────────────────────────

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        await _send_error(
            sender_uid,
            code="INVALID_TYPING",
            message="conversationId must be a non-empty string.",
        )
        return

    # ── 2. Firestore lookup ───────────────────────────────────────────────────

    try:
        doc_ref = db.collection("conversations").document(conversation_id)
        doc_snapshot = await asyncio.to_thread(doc_ref.get)
    except Exception:
        logger.exception("Firestore error fetching conversation %s", conversation_id)
        return  # typing is best-effort; no error surfaced to client

    if not doc_snapshot.exists:
        return  # silently ignore — may be a stale conversationId

    conv_data: dict[str, Any] = doc_snapshot.to_dict() or {}
    participants: list[str] = conv_data.get("participants", [])

    if sender_uid not in participants:
        return  # not a participant; silently ignore

    # ── 3. Identify the other participant ─────────────────────────────────────

    others = [uid for uid in participants if uid != sender_uid]
    if not others:
        return  # no one else to notify

    # ── 4. Deliver TypingEvent to the other participant only ──────────────────

    event: TypingEvent = {
        "type": "typing",
        "conversationId": conversation_id,
        "senderUid": sender_uid,
    }

    for uid in others:
        await manager.send_to(uid, event)

    logger.debug("typing | conv=%s | from=%s", conversation_id, sender_uid)


# ---------------------------------------------------------------------------
# handle_reaction
# ---------------------------------------------------------------------------

async def handle_reaction(sender_uid: str, payload: dict[str, Any]) -> None:
    """Handle ``{"type": "reaction", "conversationId": str, "messageId": str, "emoji": str}``.

    Parameters
    ----------
    sender_uid:
        UID of the already-authenticated user who sent this payload.
    payload:
        The full parsed JSON dict from the WebSocket frame.

    Flow
    ----
    1. Validate *conversationId*, *messageId*, and *emoji* (non-empty, ≤ 10 chars).
    2. Fetch the conversation from Firestore; verify sender is a participant.
    3. Build ReactionEvent and deliver it to ALL participants (sender included).
    """
    conversation_id: Any = payload.get("conversationId")
    message_id: Any = payload.get("messageId")
    emoji: Any = payload.get("emoji")

    # ── 1. Validate inputs ────────────────────────────────────────────────────

    if not isinstance(emoji, str) or not emoji.strip():
        await _send_error(
            sender_uid,
            code="INVALID_REACTION",
            message="emoji must be a non-empty string.",
        )
        return

    if len(emoji) > _MAX_EMOJI:
        await _send_error(
            sender_uid,
            code="INVALID_REACTION",
            message=f"emoji exceeds the {_MAX_EMOJI}-character limit.",
        )
        return

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        await _send_error(
            sender_uid,
            code="INVALID_REACTION",
            message="conversationId must be a non-empty string.",
        )
        return

    if not isinstance(message_id, str) or not message_id.strip():
        await _send_error(
            sender_uid,
            code="INVALID_REACTION",
            message="messageId must be a non-empty string.",
        )
        return

    # ── 2. Firestore lookup ───────────────────────────────────────────────────

    try:
        doc_ref = db.collection("conversations").document(conversation_id)
        doc_snapshot = await asyncio.to_thread(doc_ref.get)
    except Exception:
        logger.exception("Firestore error fetching conversation %s", conversation_id)
        await _send_error(
            sender_uid,
            code="SERVER_ERROR",
            message="Could not fetch the conversation. Please try again.",
        )
        return

    if not doc_snapshot.exists:
        await _send_error(
            sender_uid,
            code="NOT_PARTICIPANT",
            message="Conversation not found or you are not a participant.",
        )
        return

    conv_data: dict[str, Any] = doc_snapshot.to_dict() or {}
    participants: list[str] = conv_data.get("participants", [])

    if sender_uid not in participants:
        await _send_error(
            sender_uid,
            code="NOT_PARTICIPANT",
            message="Conversation not found or you are not a participant.",
        )
        return

    # ── 3. Build and deliver ReactionEvent to all participants ────────────────

    event: ReactionEvent = {
        "type": "reaction",
        "conversationId": conversation_id,
        "messageId": message_id,
        "emoji": emoji,
        "reactorUid": sender_uid,
    }

    for uid in participants:
        await manager.send_to(uid, event)

    logger.info(
        "reaction %r | conv=%s | msg=%s | from=%s",
        emoji,
        conversation_id,
        message_id,
        sender_uid,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _send_error(uid: str, *, code: str, message: str) -> None:
    err: ErrorEvent = {"type": "error", "code": code, "message": message}
    await manager.send_to(uid, err)
    logger.debug("ErrorEvent → %s  code=%s", uid, code)
