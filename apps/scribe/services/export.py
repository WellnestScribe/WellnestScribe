"""Export helpers: copy text, share link, QR code, WhatsApp deep link."""

from __future__ import annotations

import base64
import io
import secrets
from datetime import timedelta
from urllib.parse import quote

import qrcode
from django.utils import timezone


def make_share_token() -> tuple[str, "timezone.datetime"]:
    """Return (token, expires_at). 1-hour expiry by default."""
    return secrets.token_urlsafe(24), timezone.now() + timedelta(hours=1)


def qr_data_url(payload: str) -> str:
    """Return a data: URL containing a PNG QR code for the given payload."""
    img = qrcode.make(payload, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def whatsapp_url(text: str) -> str:
    """Build a wa.me share link with the note text."""
    return f"https://wa.me/?text={quote(text)}"
