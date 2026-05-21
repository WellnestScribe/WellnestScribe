"""Backend registry.

Call `get_backend()` anywhere to get the configured EMR backend instance.
The backend is selected via the EMR_BACKEND Django setting:

  EMR_BACKEND = "local"       # default — WellnestScribe's built-in EMR
  EMR_BACKEND = "gnuhealth"   # GNU Health via Docker (Tryton XML-RPC)

GNU Health connection parameters come from settings:
  GNUHEALTH_HOST, GNUHEALTH_PORT, GNUHEALTH_DB, GNUHEALTH_USER, GNUHEALTH_PASSWORD
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import EMRBackend

_lock = threading.Lock()
_instances: dict[str, "EMRBackend"] = {}


def get_backend(name: str | None = None) -> "EMRBackend":
    """Return a (cached) backend instance for *name* (defaults to settings.EMR_BACKEND)."""
    from django.conf import settings

    backend_name = name or getattr(settings, "EMR_BACKEND", "local")

    with _lock:
        if backend_name not in _instances:
            _instances[backend_name] = _build(backend_name)
    return _instances[backend_name]


def _build(name: str) -> "EMRBackend":
    from django.conf import settings

    if name == "gnuhealth":
        from .gnuhealth_backend import GnuHealthBackend

        return GnuHealthBackend(
            host=getattr(settings, "GNUHEALTH_HOST", "localhost"),
            port=int(getattr(settings, "GNUHEALTH_PORT", 8069)),
            db=getattr(settings, "GNUHEALTH_DB", "gnuhealth"),
            user=getattr(settings, "GNUHEALTH_USER", "admin"),
            password=getattr(settings, "GNUHEALTH_PASSWORD", ""),
        )

    if name == "local":
        from .local_backend import LocalEMRBackend

        return LocalEMRBackend()

    raise ValueError(
        f"Unknown EMR_BACKEND: {name!r}. "
        "Choose 'local' or 'gnuhealth' (see wellnest/settings.py)."
    )
