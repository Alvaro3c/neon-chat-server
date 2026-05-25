"""Pydantic models for incoming WebSocket event payloads.

Each class corresponds to one ``type`` value that can arrive in the
WebSocket receive loop.  They are used for structural / type validation
only; business-logic checks (e.g. Firestore membership) remain in the
individual handlers.

All models use ``model_config = ConfigDict(extra="allow")`` so that unknown
extra fields are ignored rather than raising a validation error — this keeps
the protocol forward-compatible when the client sends newer fields that the
server does not yet know about.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared limits  (mirrors the constants already defined in router / handlers)
# ---------------------------------------------------------------------------

_MAX_TEXT: int = 2_000
_MAX_EMOJI: int = 10
_MAX_MOOD: int = 140


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    """Common config for all incoming schemas."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Incoming event schemas
# ---------------------------------------------------------------------------


class AuthEvent(_Base):
    """``{"type": "auth", "token": "<firebase-id-token>"}``"""

    type: Literal["auth"]
    token: str = Field(min_length=1)


class RefreshTokenEvent(_Base):
    """``{"type": "refresh_token", "token": "<firebase-id-token>"}``"""

    type: Literal["refresh_token"]
    token: str = Field(min_length=1)


class MessageEvent(_Base):
    """``{"type": "message", "conversationId": str, "text": str}``"""

    type: Literal["message"]
    conversationId: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=_MAX_TEXT)


class ReactionEvent(_Base):
    """``{"type": "reaction", "conversationId": str, "messageId": str, "emoji": str}``"""

    type: Literal["reaction"]
    conversationId: str = Field(min_length=1)
    messageId: str = Field(min_length=1)
    emoji: str = Field(min_length=1, max_length=_MAX_EMOJI)


class TypingEvent(_Base):
    """``{"type": "typing", "conversationId": str}``"""

    type: Literal["typing"]
    conversationId: str = Field(min_length=1)


class StatusUpdateEvent(_Base):
    """``{"type": "status_update", "status": str}``

    Accepts any non-empty string.  The full list of valid values is defined
    client-side in ``USER_STATUSES`` (``online``, ``away``, ``busy``,
    ``offline``, ``sober``, ``breaking``, ``noregret``, ``train``,
    ``misrep``, ``scotty``); the server stores and forwards the value
    verbatim — dot-colour and label resolution are the front-end's
    responsibility.
    """

    type: Literal["status_update"]
    status: str = Field(min_length=1)


class MoodUpdateEvent(_Base):
    """``{"type": "mood_update", "mood": str}``  — mood is at most 140 chars."""

    type: Literal["mood_update"]
    mood: str = Field(max_length=_MAX_MOOD)
