"""Application-level PHI field encryption using Fernet (AES-128-CBC + HMAC-SHA256).

Every field that stores patient-identifiable data (name, identifier, transcripts,
note content) uses EncryptedTextField or EncryptedCharField. Ciphertext is stored
in the database; plaintext only ever lives in Python memory during a request.

SETUP (one-time):
    1. Generate a key:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    2. Set  FIELD_ENCRYPTION_KEY=<key>  in .env / Azure App Service Application Settings.
    3. Encrypt existing rows (run once after deploying the key):
       python manage.py encrypt_existing_phi

ZERO-DOWNTIME FALLBACK:
    If FIELD_ENCRYPTION_KEY is absent the fields behave exactly like their base
    Django counterparts — no crash, no data loss. Safe for local dev and for the
    first deploy before the key is configured.

KEY ROTATION (future):
    Set FIELD_ENCRYPTION_KEY_PREVIOUS to the old key and FIELD_ENCRYPTION_KEY to the
    new one, then run  manage.py encrypt_existing_phi  — it re-encrypts with the new key.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Core encrypt / decrypt helpers
# ---------------------------------------------------------------------------

def _fernet() -> Fernet | None:
    key = (getattr(settings, "FIELD_ENCRYPTION_KEY", None) or "").strip()
    if not key:
        return None
    raw = key.encode() if isinstance(key, str) else key
    return Fernet(raw)


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 Fernet token string."""
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(stored: str) -> str:
    """Decrypt a Fernet token.  Falls back to *stored* for legacy plaintext rows."""
    f = _fernet()
    if f is None:
        return stored
    try:
        return f.decrypt(stored.encode()).decode()
    except (InvalidToken, Exception):
        # Row was written before encryption was enabled — return raw value so
        # existing data stays readable until encrypt_existing_phi is run.
        return stored


# ---------------------------------------------------------------------------
# Custom model field classes
# ---------------------------------------------------------------------------

class EncryptedTextField(models.TextField):
    """TextField that transparently encrypts on write and decrypts on read.

    Backward-compatible: unencrypted rows are returned as-is (decryption
    falls through gracefully).  Running  manage.py encrypt_existing_phi
    brings all rows up to date.
    """

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return decrypt_value(value)

    def get_prep_value(self, value):
        if not value:
            return value
        return encrypt_value(value)


class EncryptedCharField(EncryptedTextField):
    """Encrypted CharField.

    Stored as a TEXT column because Fernet ciphertext is ~100 bytes longer
    than the plaintext, so VARCHAR(n) cannot hold it.  max_length is kept
    for form-level validation only.
    """

    def __init__(self, *args, max_length: int = 255, **kwargs):
        self.max_length = max_length
        super().__init__(*args, **kwargs)

    def db_type(self, connection) -> str:
        return "text"

    def get_internal_type(self) -> str:
        return "TextField"

    def formfield(self, **kwargs):
        defaults = {"max_length": self.max_length}
        defaults.update(kwargs)
        return super().formfield(**defaults)
