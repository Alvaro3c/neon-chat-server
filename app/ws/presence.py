"""Presence helpers — Firestore-based contact lookup.

Provides ``get_contact_uids``, the single source of truth for "who should
receive a presence event for this user?".  All callers (on-connect,
on-disconnect, status_update, mood_update) use this function so the logic
lives in exactly one place.
"""

from __future__ import annotations

import asyncio
import logging

from google.cloud.firestore_v1.base_query import FieldFilter

from app.db import db

logger = logging.getLogger(__name__)


async def get_contact_uids(uid: str) -> list[str]:
    """Return UIDs of users who share ≥1 active conversation with *uid*.

    Queries Firestore for every conversation document where
    ``participants`` array contains *uid* **and** ``status == "active"``,
    then returns the unique set of OTHER participant UIDs found in those
    documents.

    The synchronous Firestore I/O is offloaded to a thread-pool executor
    via ``asyncio.to_thread`` so the async event loop is never blocked.

    Parameters
    ----------
    uid:
        The Firebase UID whose contacts we want to resolve.

    Returns
    -------
    list[str]
        Deduplicated list of contact UIDs (order is arbitrary).
        Returns an empty list if *uid* has no active conversations or if
        the Firestore query fails (the error is logged but not re-raised).
    """

    def _query() -> list[str]:
        docs = (
            db.collection("conversations")
            .where(filter=FieldFilter("participants", "array_contains", uid))
            .where(filter=FieldFilter("status", "==", "active"))
            .stream()
        )
        seen: set[str] = set()
        contacts: list[str] = []
        for doc in docs:
            data = doc.to_dict() or {}
            for participant in data.get("participants", []):
                if participant != uid and participant not in seen:
                    seen.add(participant)
                    contacts.append(participant)
        return contacts

    try:
        return await asyncio.to_thread(_query)
    except Exception:
        logger.exception("get_contact_uids: Firestore error for uid=%s", uid)
        return []
