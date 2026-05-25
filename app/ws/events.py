from typing import Literal
from typing import TypedDict


class AuthOkEvent(TypedDict):
    type: Literal["auth_ok"]
    uid: str
    displayName: str
    email: str
    photoURL: str


class AuthErrorEvent(TypedDict):
    type: Literal["auth_error"]
    message: str


class MessageEvent(TypedDict):
    type: Literal["message"]
    conversationId: str
    messageId: str
    senderUid: str
    senderName: str
    text: str
    timestamp: str


class ReactionEvent(TypedDict):
    type: Literal["reaction"]
    conversationId: str
    messageId: str
    emoji: str
    reactorUid: str


class TypingEvent(TypedDict):
    type: Literal["typing"]
    conversationId: str
    senderUid: str


class ContactStatusEvent(TypedDict):
    type: Literal["contact_status"]
    uid: str
    status: str
    mood: str


class ContactProfileEvent(TypedDict):
    """Sent to contacts when a user changes their custom nickname or photo.

    ``displayName`` is the effective display name to show (custom nick if set,
    otherwise the Google account name).  ``photoURL`` is included so clients
    can update the avatar in one round-trip if it ever changes.
    """

    type: Literal["contact_profile"]
    uid: str
    displayName: str
    photoURL: str


class ErrorEvent(TypedDict):
    type: Literal["error"]
    code: str
    message: str
