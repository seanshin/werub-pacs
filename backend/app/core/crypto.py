"""Symmetric encryption for credentials stored at rest.

Derives a stable Fernet key from ``settings.secret_key`` so that secrets such as
external PACS peer passwords are never persisted in plaintext. The same secret
that protects JWTs protects these credentials — rotating it invalidates both.

Usage::

    from app.core.crypto import encrypt_secret, decrypt_secret

    stored = encrypt_secret(plaintext)      # -> str | None
    plaintext = decrypt_secret(stored)      # -> str | None
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

# Marker prefix so we can tell encrypted values apart from legacy plaintext
# rows that may still exist in the DB (graceful migration without a backfill).
_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    """Derive a urlsafe-base64 32-byte Fernet key from the app secret."""
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. Returns ``None`` for empty input."""
    if not plaintext:
        return None
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt_secret(stored: str | None) -> str | None:
    """Decrypt a stored secret.

    Backward compatible: values without the ``enc:v1:`` prefix are assumed to be
    legacy plaintext and returned as-is (logged once at WARNING). Corrupt tokens
    return ``None``.
    """
    if not stored:
        return None
    if not stored.startswith(_PREFIX):
        logger.warning("decrypt_secret: legacy plaintext credential read — re-save to encrypt")
        return stored
    try:
        token = stored[len(_PREFIX):].encode("ascii")
        return _fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("decrypt_secret: failed to decrypt credential (key rotated or corrupt)")
        return None
