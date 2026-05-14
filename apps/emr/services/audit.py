"""Structured audit logging for EMR interactions."""

from __future__ import annotations

from emr.models import AuditLog


def log_audit_event(request, organisation, *, action, resource_type="", resource_id="", detail="", changes=None):
    AuditLog.objects.create(
        organisation=organisation,
        user=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id or ""),
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        detail=detail[:2000],
        changes=changes or {},
    )
