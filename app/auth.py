"""Firebase Admin initialisation and ID-token verification."""

import asyncio
import json

import firebase_admin
import firebase_admin.auth
from firebase_admin import credentials

from app.config import settings

# ── one-time initialisation ──────────────────────────────────────────────────
if not firebase_admin._apps:
    if settings.firebase_service_account_json:
        # Producción (Render, etc.): JSON completo en variable de entorno
        _cred = credentials.Certificate(json.loads(settings.firebase_service_account_json))
    elif settings.firebase_service_account_path:
        # Desarrollo local: ruta a fichero JSON
        _cred = credentials.Certificate(settings.firebase_service_account_path)
    else:
        raise RuntimeError(
            "Firebase credentials not configured. "
            "Set FIREBASE_SERVICE_ACCOUNT_JSON (production) "
            "or FIREBASE_SERVICE_ACCOUNT_PATH (local)."
        )
    firebase_admin.initialize_app(_cred)


# ── public API ───────────────────────────────────────────────────────────────

async def verify_id_token(token: str) -> dict:
    """Verify a Firebase ID token and return its decoded claims.

    Parameters
    ----------
    token:
        The raw JWT string issued by Firebase Auth on the client side.

    Returns
    -------
    dict
        Decoded token claims including at minimum: ``uid``, ``email``,
        ``name``, and ``picture``.

    Raises
    ------
    ValueError
        If the token is invalid, expired, revoked, or cannot be verified
        for any other reason.
    """
    try:
        decoded = await asyncio.to_thread(
            firebase_admin.auth.verify_id_token, token
        )
        return dict(decoded)
    except firebase_admin.auth.RevokedIdTokenError as exc:
        raise ValueError("ID token has been revoked.") from exc
    except firebase_admin.auth.ExpiredIdTokenError as exc:
        raise ValueError("ID token has expired.") from exc
    except firebase_admin.auth.InvalidIdTokenError as exc:
        raise ValueError(f"ID token is invalid: {exc}") from exc
    except Exception as exc:  # catch-all for unexpected SDK errors
        raise ValueError(f"Token verification failed: {exc}") from exc
