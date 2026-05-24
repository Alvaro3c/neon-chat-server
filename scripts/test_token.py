"""Standalone script to verify a Firebase ID token against the backend auth module.

Usage
-----
    python scripts/test_token.py <firebase-id-token>

The script initialises Firebase Admin (via app/auth.py) using the service-account
path from .env, then prints the decoded token claims on success or a clear error
message on failure.
"""

import asyncio
import sys
from pathlib import Path

# Allow running from the repo root *or* from the backend/ directory.
# Either way we need 'backend/' on sys.path so `from app.auth import …` works.
_here = Path(__file__).resolve()
_backend = _here.parent.parent          # …/backend/
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Load .env before importing app.config (pydantic-settings reads it at import time).
from dotenv import load_dotenv  # noqa: E402 — must come after sys.path fix

load_dotenv(_backend / ".env")

from app.auth import verify_id_token  # noqa: E402


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_token.py <firebase-id-token>")
        sys.exit(1)

    token = sys.argv[1]

    try:
        claims = await verify_id_token(token)
        print("✅  Token verified successfully.\n")
        print("Decoded claims:")
        for key, value in claims.items():
            print(f"  {key}: {value}")
    except ValueError as exc:
        print(f"❌  Verification failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
