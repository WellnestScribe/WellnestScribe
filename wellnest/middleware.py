"""Security audit middleware for WellNest Scribe.

Runs on every request after authentication is resolved.  Detects and logs
suspicious patterns; sends email alerts to SECURITY_ALERT_EMAIL when
a threshold is crossed.

Patterns monitored:
  • Rapid page access: >60 authenticated requests in 60 s from the same IP
    (scraping / automated data extraction).
  • Impossible travel: same account from two IPs that geolocate to different
    countries within 30 minutes (account sharing / credential theft).
    Note: geolocation is IP-prefix heuristic only — not perfectly reliable.
  • Repeated 403/401 responses: >10 in 5 minutes from the same IP
    (probing for unauthorised endpoints).

All events are written to the  scribe.audit  logger (audit.log).  Email alerts
are rate-limited to one per pattern-type per IP per hour so the inbox does not
flood during a sustained attack.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from django.conf import settings

audit_log = logging.getLogger("scribe.audit")
security_log = logging.getLogger("scribe")

# ── In-memory sliding-window counters ────────────────────────────────────────
# These are per-process; adequate for single-instance pilots.
# Replace with Redis/cache backend when scaling to multiple processes.

_lock = threading.Lock()

# {ip: deque of timestamps} — for rapid-access detection
_ip_request_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

# {ip: deque of timestamps} — for 403/401 probing detection
_ip_error_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))

# {user_id: (ip, timestamp)} — for impossible-travel detection
_user_last_ip: dict[int, tuple[str, float]] = {}

# {(alert_type, ip): last_alert_timestamp} — rate-limit email sends
_alert_sent_at: dict[tuple, float] = {}

RAPID_ACCESS_WINDOW_S = 60
RAPID_ACCESS_LIMIT = 60

ERROR_PROBE_WINDOW_S = 300
ERROR_PROBE_LIMIT = 10

IMPOSSIBLE_TRAVEL_WINDOW_S = 1800  # 30 min
# We detect "different /8 subnet" as a simple impossible-travel proxy
# (works for obvious VPN/country hops; won't catch same-country IP changes)

ALERT_COOLDOWN_S = 3600  # send at most one email per alert-type per IP per hour


def _send_alert(subject: str, body: str, alert_key: tuple) -> None:
    """Send a security alert email if not rate-limited."""
    now = time.monotonic()
    last = _alert_sent_at.get(alert_key, 0)
    if now - last < ALERT_COOLDOWN_S:
        return
    _alert_sent_at[alert_key] = now

    recipient = getattr(settings, "SECURITY_ALERT_EMAIL", "")
    if not recipient:
        return
    try:
        from django.core.mail import send_mail
        send_mail(
            subject=f"[WellNest Security] {subject}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wellnestscribe.com"),
            recipient_list=[recipient],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001
        pass


def _ip_prefix(ip: str) -> str:
    """Return the first two octets of an IPv4 address (rough geo-class proxy)."""
    parts = (ip or "").split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return ip


class SecurityAuditMiddleware:
    """Lightweight request-level security monitoring."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._audit(request, response)
        return response

    def _audit(self, request, response) -> None:
        ip = self._get_ip(request)
        now = time.monotonic()

        with _lock:
            # ── Rapid access detection ────────────────────────────────────
            if request.user.is_authenticated:
                times = _ip_request_times[ip]
                times.append(now)
                cutoff = now - RAPID_ACCESS_WINDOW_S
                recent = sum(1 for t in times if t >= cutoff)
                if recent >= RAPID_ACCESS_LIMIT:
                    audit_log.warning(
                        "RAPID_ACCESS ip=%s user=%s requests=%d in %ds",
                        ip, request.user.pk, recent, RAPID_ACCESS_WINDOW_S,
                    )
                    _send_alert(
                        "Rapid access detected",
                        f"IP {ip} made {recent} requests in {RAPID_ACCESS_WINDOW_S}s "
                        f"as user {request.user}.\nPath: {request.path}",
                        ("rapid_access", ip),
                    )

            # ── Impossible travel detection ───────────────────────────────
            if request.user.is_authenticated:
                uid = request.user.pk
                prev = _user_last_ip.get(uid)
                if prev:
                    prev_ip, prev_ts = prev
                    if (
                        _ip_prefix(ip) != _ip_prefix(prev_ip)
                        and now - prev_ts < IMPOSSIBLE_TRAVEL_WINDOW_S
                    ):
                        audit_log.warning(
                            "IMPOSSIBLE_TRAVEL user=%s prev_ip=%s new_ip=%s gap_s=%.0f",
                            uid, prev_ip, ip, now - prev_ts,
                        )
                        _send_alert(
                            "Impossible travel — possible account takeover",
                            f"User {request.user} logged in from {prev_ip} then {ip} "
                            f"within {int(now - prev_ts)}s.\n"
                            f"Path: {request.path}",
                            ("impossible_travel", str(uid)),
                        )
                _user_last_ip[uid] = (ip, now)

            # ── 403 / 401 probing detection ───────────────────────────────
            if response.status_code in (401, 403):
                times = _ip_error_times[ip]
                times.append(now)
                cutoff = now - ERROR_PROBE_WINDOW_S
                recent = sum(1 for t in times if t >= cutoff)
                if recent >= ERROR_PROBE_LIMIT:
                    audit_log.warning(
                        "ERROR_PROBING ip=%s count=%d status=%d",
                        ip, recent, response.status_code,
                    )
                    _send_alert(
                        "Endpoint probing detected",
                        f"IP {ip} triggered {recent} {response.status_code} responses "
                        f"in {ERROR_PROBE_WINDOW_S}s.\nLast path: {request.path}",
                        ("error_probing", ip),
                    )

    @staticmethod
    def _get_ip(request) -> str:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


# Paths a locked-out non-admin may still reach, so they can read the notice,
# sign out, and load styling. Everything else is blocked in MODE_LOCKED.
_LOCKDOWN_ALLOW_PREFIXES = (
    "/accounts/signin",
    "/accounts/signup",
    "/accounts/signout",
    "/accounts/api/reauth",
    "/static/",
    "/media/",
    "/favicon",
    "/manifest",
    "/sw.js",
    "/serviceworker",
)


class DemoLockdownMiddleware:
    """Enforce PlatformControl's *Locked* demo mode for non-admin users.

    When an admin sets demo_mode to 'locked' (e.g. during a public pitch where
    a sign-up QR is on screen), every non-admin request outside the allow-list
    is short-circuited: API/POST calls get a JSON 403, page loads get a friendly
    "test mode" screen. This is the global chokepoint that protects model
    credits even on endpoints added later — it sits in front of every view.

    'Test mode' (limited) is NOT handled here; that is a per-session count
    enforced where sessions are created, so users can still finish their one
    allowed note.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        blocked = self._should_block(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)

    def _should_block(self, request):
        path = request.path
        if path.startswith(_LOCKDOWN_ALLOW_PREFIXES):
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None  # anonymous users can't run the pipeline anyway

        # Local imports: middleware is imported before apps are ready.
        from accounts.models import PlatformControl, user_is_admin

        try:
            control = PlatformControl.get()
        except Exception:  # noqa: BLE001 — never let the gate take the site down
            return None
        if control.demo_mode != PlatformControl.MODE_LOCKED:
            return None
        if user_is_admin(user):
            return None

        message = control.message_for_mode()
        wants_json = (
            request.method == "POST"
            or "/api/" in path
            or "application/json" in request.headers.get("accept", "")
            or request.headers.get("x-requested-with") == "XMLHttpRequest"
        )
        if wants_json:
            from django.http import JsonResponse
            return JsonResponse(
                {"ok": False, "error": message, "demo_locked": True}, status=403
            )
        from django.shortcuts import render
        return render(
            request, "accounts/demo_locked.html", {"message": message}, status=403
        )
