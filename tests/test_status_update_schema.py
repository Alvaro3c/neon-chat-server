"""Unit tests for StatusUpdateEvent validation.

The schema accepts any non-empty string and forwards it verbatim.
All label resolution and dot-colour mapping is the front-end's
responsibility (see USER_STATUSES in ConversationSidebar).

Run with:
    pytest tests/test_status_update_schema.py -v
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ws.schemas import StatusUpdateEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(status: str) -> StatusUpdateEvent:
    return StatusUpdateEvent.model_validate({"type": "status_update", "status": status})


# ---------------------------------------------------------------------------
# Canonical values pass through unchanged
# ---------------------------------------------------------------------------

class TestCanonicalStatus:
    @pytest.mark.parametrize("value", ["online", "away", "busy", "offline"])
    def test_canonical_status_preserved(self, value: str) -> None:
        assert _parse(value).status == value


# ---------------------------------------------------------------------------
# App-specific values pass through unchanged (no server-side mapping)
# ---------------------------------------------------------------------------

class TestCustomStatus:
    @pytest.mark.parametrize(
        "value",
        ["sober", "breaking", "noregret", "train", "misrep", "scotty"],
    )
    def test_custom_status_preserved_verbatim(self, value: str) -> None:
        """Custom status values must reach contacts exactly as the user chose them."""
        assert _parse(value).status == value

    def test_no_display_status_field(self) -> None:
        """The schema no longer carries a display_status field."""
        event = _parse("train")
        assert not hasattr(event, "display_status")


# ---------------------------------------------------------------------------
# Unknown values also pass through (schema is permissive on purpose)
# ---------------------------------------------------------------------------

class TestUnknownStatus:
    @pytest.mark.parametrize("value", ["vibing", "grind", "do-not-disturb", "🚂"])
    def test_unknown_status_preserved(self, value: str) -> None:
        assert _parse(value).status == value


# ---------------------------------------------------------------------------
# Empty string is rejected (min_length=1)
# ---------------------------------------------------------------------------

class TestInvalidStatus:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            _parse("")
