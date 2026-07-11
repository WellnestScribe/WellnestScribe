"""Views for the WellNest Scribe MVP.

Page views render templates; API views are JSON-in/JSON-out and are used by the
browser-side recorder and editor.
"""

from __future__ import annotations

import json
import logging
import re
import time

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from django.conf import settings as dj_settings

from accounts.models import DoctorProfile

from .models import ModalOmniEndpoint, NoteShare, NoteFeedback, ScribeSession, SessionEvent, SOAPNote
from .services.export import make_share_token, qr_data_url
from .services.pipeline import (
    run_extract_demographics,
    run_interpret_and_generate_soap,
    run_interpret_for_lang,
    run_interpret_patois,
    run_note_generation,
    run_polish_grammar,
    run_stream_note_generation,
    run_suggest_improvements,
    run_transcription,
)
from .services.triage import (
    TriageDependencyError,
    _compute_wer_cer,
    probe_environment,
    transcribe_mms,
    transcribe_modal_mms,  # TEMPORARY — Modal GPU latency testing
    transcribe_modal_omni,
    transcribe_gradio,
    transcribe_omni,
    transcribe_parakeet,
    t5_rewrite,
)
from .services.triage_jobs import get as get_triage_job, reap_old, submit as submit_triage_job


def _triage_visible(user) -> bool:
    """Can the user see the Triage page at all? Controlled by env flag too."""
    if not user.is_authenticated:
        return False
    if dj_settings.SCRIBE_ENABLE_TRIAGE:
        return True
    profile = DoctorProfile.objects.filter(user=user).first()
    if profile and profile.can_access_triage():
        return True
    return bool(user.is_staff or user.is_superuser)


def _triage_admin(user) -> bool:
    """Can the user perform privileged Triage actions (install pip, download
    models, etc.)? Admin-only regardless of SCRIBE_ENABLE_TRIAGE.

    pip install runs arbitrary code on the host — never let a regular doctor
    trigger that even if you've opened Triage to the whole pilot for testing.
    """
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    profile = DoctorProfile.objects.filter(user=user).first()
    return bool(profile and profile.is_admin)


logger = logging.getLogger(__name__)
audit_log = logging.getLogger("scribe.audit")


def _get_profile(user) -> DoctorProfile:
    profile, _ = DoctorProfile.objects.get_or_create(user=user)
    return profile


# emr.Patient.sex → scribe patient_gender. Keeps note-generation pronouns
# correct from the authoritative patient record instead of inference.
_EMR_SEX_TO_GENDER = {"male": "M", "female": "F", "intersex": "O", "unknown": ""}


def _resolve_linked_patient(user, patient_id):
    """Return an emr.Patient in the user's clinic, or None.

    Scoped through the same org resolver the EMR uses, so a doctor can only
    attach patients from their own organisation. Any emr problem returns None
    rather than breaking the recording flow (Feature 1).
    """
    if not patient_id:
        return None
    try:
        from emr.models import Patient
        from emr.services.access import get_membership
    except Exception:  # noqa: BLE001 — emr must never break recording
        return None
    try:
        ctx = get_membership(user)
        return Patient.objects.filter(pk=patient_id, organisation=ctx.organisation).first()
    except Exception:  # noqa: BLE001
        return None


def _latest_nurse_vitals(patient_id):
    """Most recent Vital recorded for a patient today (nurse intake), or None."""
    if not patient_id:
        return None
    try:
        from emr.models import Vital
        return (
            Vital.objects.filter(
                patient_id=patient_id, recorded_at__date=timezone.localdate()
            )
            .order_by("-recorded_at")
            .first()
        )
    except Exception:  # noqa: BLE001
        return None


def _nurse_vitals_context(session) -> str:
    """Nurse-measured vitals for this visit, formatted as note-generation context.

    Binds the BP / glucose / temp the nurse captured at intake to the note the
    doctor dictates, so the AI writes the real measured numbers instead of
    inventing them (S7: vitals-as-context).
    """
    v = _latest_nurse_vitals(getattr(session, "patient_id", None))
    if v is None:
        return ""
    bits = []
    if v.bp_systolic and v.bp_diastolic:
        bits.append(f"BP {v.bp_systolic}/{v.bp_diastolic} mmHg")
    if v.pulse_bpm:
        bits.append(f"pulse {v.pulse_bpm} bpm")
    if v.temperature_celsius:
        bits.append(f"temperature {v.temperature_celsius} °C")
    if v.weight_kg:
        bits.append(f"weight {v.weight_kg} kg")
    if v.oxygen_saturation:
        bits.append(f"SpO2 {v.oxygen_saturation}%")
    if v.blood_glucose_mmol:
        bits.append(f"blood glucose {v.blood_glucose_mmol} mmol/L")
    if not bits:
        return ""
    return (
        "Vitals measured by the nurse at intake today (use these exact values in the "
        "Objective / vital signs section — do not invent different numbers): "
        + ", ".join(bits)
        + "."
    )


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _log(session: ScribeSession, event_type: str, detail: str = "") -> None:
    SessionEvent.objects.create(
        session=session, event_type=event_type, detail=detail[:2000]
    )
    audit_log.info(
        "session=%s doctor=%s event=%s detail=%s",
        session.pk,
        session.doctor_id,
        event_type,
        detail.replace("\n", " ")[:400],
    )


# ----- Page views -----

class RecordView(LoginRequiredMixin, View):
    template_name = "scribe/record.html"

    def get(self, request):
        profile = _get_profile(request.user)
        recent = (
            ScribeSession.objects.filter(doctor=request.user)
            .order_by("-created_at")[:6]
        )
        # Feature 1: patient-first entry. ?patient=<id> preselects and locks the
        # patient so the doctor records straight into that patient's history.
        selected_patient = _resolve_linked_patient(request.user, request.GET.get("patient"))
        selected_patient_vitals = _latest_nurse_vitals(selected_patient.pk) if selected_patient else None
        scribe_enabled, subscription_expires = True, None
        try:
            from emr.services.access import get_membership
            _org = get_membership(request.user).organisation
            scribe_enabled = _org.scribe_enabled
            subscription_expires = _org.subscription_expires
        except Exception:  # noqa: BLE001
            pass
        return render(
            request,
            self.template_name,
            {
                "profile": profile,
                "recent_sessions": recent,
                "selected_patient": selected_patient,
                "selected_patient_vitals": selected_patient_vitals,
                "scribe_enabled": scribe_enabled,
                "subscription_expires": subscription_expires,
                "specialty_choices": DoctorProfile.SPECIALTY_CHOICES,
                "format_choices": ScribeSession.NOTE_FORMAT_CHOICES,
                "length_choices": ScribeSession.LENGTH_MODE_CHOICES,
                # TEMPORARY — Modal GPU latency testing toggle
                "ambient_backend": dj_settings.AMBIENT_BACKEND,
                "stream_generation": dj_settings.SCRIBE_STREAM_GENERATION,
            },
        )


def _group_unlinked_sessions(sessions):
    """Group scribe sessions with no linked emr.Patient by (name, identifier).

    Covers walk-ins recorded before the patient was registered — still
    searchable, but they carry no patient_id (chart link) until linked.
    """
    seen: dict = {}
    for s in sessions:
        name = (s["patient_name"] or "").strip()
        if not name:
            continue
        ident = (s["patient_identifier"] or "").strip()
        key = (name.lower(), ident.lower())
        if key not in seen:
            seen[key] = {
                "patient_id": "",
                "name": name,
                "identifier": ident,
                "gender": s["patient_gender"] or "",
                "last_pk": s["pk"],
                "last_cc": s["chief_complaint"] or "",
                "last_visit": s["created_at"].strftime("%b %d, %Y"),
                "session_count": 1,
            }
        else:
            seen[key]["session_count"] += 1
    return list(seen.values())


@login_required
def patients_api(request):
    """Every patient registered to the doctor's clinic — shared across the whole
    facility, not just this doctor's own sessions.

    Pulls the authoritative roster from emr.Patient (so a colleague's patients,
    and seeded/registered patients who were never scribed, all show up), then
    folds in any unlinked walk-in sessions from clinic staff. Each registered
    result carries a real ``patient_id`` so selecting it links the chart.
    """
    results: list = []

    try:
        from emr.models import OrganisationMembership, Patient
        from emr.services.access import get_membership
        org = get_membership(request.user).organisation
    except Exception:  # noqa: BLE001 — never break recording if EMR is unavailable
        org = None

    if org is not None:
        patients = (
            Patient.objects.filter(organisation=org)
            .prefetch_related("scribe_sessions")
            .order_by("legal_last_name", "legal_first_name")[:500]
        )
        for p in patients:
            sess = sorted(
                p.scribe_sessions.all(), key=lambda s: s.created_at, reverse=True
            )
            last = sess[0] if sess else None
            results.append({
                "patient_id": p.pk,
                "name": p.display_name,
                "identifier": (p.trn or p.nhf_card_number or p.mrn or "").strip(),
                "gender": _EMR_SEX_TO_GENDER.get((p.sex or "").lower(), ""),
                "last_pk": last.pk if last else "",
                "last_cc": (getattr(last, "chief_complaint", "") or "") if last else "",
                "last_visit": last.created_at.strftime("%b %d, %Y") if last else "Registered",
                "session_count": len(sess),
            })

        # Fold in unlinked walk-in sessions recorded by anyone in the clinic.
        member_ids = OrganisationMembership.objects.filter(
            organisation=org
        ).values_list("user_id", flat=True)
        unlinked = (
            ScribeSession.objects.filter(doctor_id__in=list(member_ids), patient__isnull=True)
            .exclude(patient_name="")
            .order_by("-created_at")
            .values("pk", "patient_name", "patient_identifier", "patient_gender", "chief_complaint", "created_at")
        )
        results.extend(_group_unlinked_sessions(unlinked))
    else:
        # Fallback: this doctor's own sessions only (no clinic context).
        own = (
            ScribeSession.objects.filter(doctor=request.user)
            .exclude(patient_name="")
            .order_by("-created_at")
            .values("pk", "patient_name", "patient_identifier", "patient_gender", "chief_complaint", "created_at")
        )
        results.extend(_group_unlinked_sessions(own))

    # Mark names that appear more than once so the UI can show a disambiguator.
    name_freq: dict = {}
    for r in results:
        name_freq[r["name"].lower()] = name_freq.get(r["name"].lower(), 0) + 1
    for r in results:
        r["ambiguous"] = name_freq[r["name"].lower()] > 1

    return JsonResponse({"patients": results})


@login_required
def recent_sessions_api(request):
    """JSON of the doctor's latest sessions so the record page can refresh the
    Recent-sessions list live (no page reload after finishing a note)."""
    qs = ScribeSession.objects.filter(doctor=request.user).order_by("-created_at")[:8]
    sessions = [{
        "pk": s.pk,
        "name": s.patient_name or s.created_at.strftime("%b %d, %Y"),
        "meta": s.created_at.strftime("%b %d · %I:%M %p")
                + (f" · {s.chief_complaint[:38]}" if s.chief_complaint else ""),
        "status": s.status,
        "status_label": s.get_status_display(),
        "sensitive": bool(s.is_sensitive),
        "review_url": f"/scribe/sessions/{s.pk}/review/",
        "search": f"{(s.patient_name or '').lower()} {(s.chief_complaint or '').lower()}",
    } for s in qs]
    return JsonResponse({"sessions": sessions})


@login_required
def patient_recent_notes_api(request, patient_id):
    """Last few notes for a patient so the doctor can skim before recording (S2).

    No AI — returns the stored note text (visit summary / assessment excerpt)
    plus a link to open the full note. Scoped to the user's organisation.
    """
    patient = _resolve_linked_patient(request.user, patient_id)
    if patient is None:
        return JsonResponse({"notes": []})
    sessions = (
        ScribeSession.objects.filter(patient=patient)
        .select_related("note")
        .order_by("-created_at")[:3]
    )
    notes = []
    for s in sessions:
        note = getattr(s, "note", None)
        summary = ""
        if note:
            summary = (note.visit_summary or note.assessment or note.full_note or "").strip()[:600]
        notes.append({
            "date": s.created_at.strftime("%b %d, %Y"),
            "complaint": s.chief_complaint or s.title or "Consultation",
            "summary": summary,
            "review_url": f"/scribe/sessions/{s.pk}/review/",
        })
    return JsonResponse({"notes": notes, "patient": patient.full_name})


class HistoryView(LoginRequiredMixin, View):
    template_name = "scribe/history.html"

    def get(self, request):
        qs = ScribeSession.objects.filter(doctor=request.user).select_related("note").order_by("-created_at")
        patient_name = request.GET.get("patient_name", "").strip()
        patient_id   = request.GET.get("patient_id", "").strip()
        if patient_name:
            qs = qs.filter(patient_name__iexact=patient_name)
        if patient_id:
            qs = qs.filter(patient_identifier__iexact=patient_id)
        return render(request, self.template_name, {
            "sessions": qs,
            "filter_patient_name": patient_name,
            "filter_patient_id": patient_id,
        })


class ReviewView(LoginRequiredMixin, View):
    template_name = "scribe/review.html"

    def get(self, request, pk):
        session = get_object_or_404(
            ScribeSession.objects.select_related("note"),
            pk=pk,
            doctor=request.user,
        )
        # Enhanced audit trail for sensitive sessions — every view is logged,
        # not just saves. Satisfies DPA 2020 access-tracking requirement.
        if session.is_sensitive:
            audit_log.info(
                "session=%s doctor=%s event=sensitive_viewed ip=%s",
                session.pk,
                session.doctor_id,
                request.META.get("REMOTE_ADDR", "unknown"),
            )
        note = getattr(session, "note", None)
        # Re-run deterministic safety checks on every view so stale DB flags
        # (from before validation logic was tightened) get corrected automatically.
        if note and note.full_note:
            from .services.soap_generator import validate_note_safety  # noqa: PLC0415
            _SAFETY_PREFIXES = ("[RANGE ALERT]", "[CONFLICTING PAIN", "[NO VITALS]", "[MINIMISING")
            ai_flags = [f for f in (note.flags or []) if not f.startswith(_SAFETY_PREFIXES)]
            fresh_safety = validate_note_safety(note.full_note, session.raw_transcript or "")
            fresh_flags = ai_flags + fresh_safety
            if fresh_flags != list(note.flags or []):
                note.flags = fresh_flags
                note.save(update_fields=["flags", "updated_at"])

        return render(
            request,
            self.template_name,
            {
                "session": session,
                "note": note,
                "profile": _get_profile(request.user),
                "doctor_profile": _get_profile(request.user),
                # NATVNS Wound Management chart adaptation. Static list of
                # "factors that could delay healing" — flat checkbox row in
                # the Body diagram tab.
                "body_healing_factors": [
                    ("immobility", "Immobility"),
                    ("poor_nutrition", "Poor nutrition"),
                    ("diabetes", "Diabetes"),
                    ("incontinence", "Incontinence"),
                    ("resp_circ_disease", "Respiratory / circulatory disease"),
                    ("anaemia", "Anaemia"),
                    ("medication", "Medication"),
                    ("wound_infection", "Wound infection"),
                    ("inotropes", "Inotropes"),
                    ("anticoagulants", "Anti-coagulants"),
                    ("oedema", "Oedema"),
                    ("steroids", "Steroids"),
                    ("chemotherapy", "Chemotherapy"),
                ],
            },
        )


class SessionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        return redirect("scribe:review", pk=pk)


class AuditLogView(LoginRequiredMixin, View):
    """Admin-only view of recent SessionEvents, paginated, with filters."""

    template_name = "scribe/audit_log.html"

    def get(self, request):
        profile = DoctorProfile.objects.filter(user=request.user).first()
        is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
        if not is_admin:
            return redirect("scribe:record")

        events = (
            SessionEvent.objects
            .select_related("session", "session__doctor")
            .order_by("-created_at")
        )
        event_type = request.GET.get("type", "").strip()
        username = request.GET.get("user", "").strip()
        if event_type:
            events = events.filter(event_type=event_type)
        if username:
            events = events.filter(session__doctor__username__icontains=username)

        events = events[:200]

        return render(
            request,
            self.template_name,
            {
                "events": events,
                "event_type_filter": event_type,
                "user_filter": username,
                "event_choices": SessionEvent.EVENT_CHOICES,
            },
        )


class FeedbackLogView(LoginRequiredMixin, View):
    """Admin view: all thumbs-down (and up) note feedback with optional comments."""

    template_name = "scribe/feedback_log.html"

    def get(self, request):
        import csv as _csv  # noqa: PLC0415
        from django.http import HttpResponse  # noqa: PLC0415

        profile = DoctorProfile.objects.filter(user=request.user).first()
        is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
        if not is_admin:
            return redirect("scribe:record")

        feedback = (
            NoteFeedback.objects
            .select_related("session", "doctor")
            .order_by("-created_at")[:500]
        )

        if request.GET.get("export") == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="wellnest_note_feedback.csv"'
            writer = _csv.writer(response)
            writer.writerow(["date", "doctor", "session_id", "session_title", "section", "rating", "comment"])
            for fb in feedback:
                writer.writerow([
                    fb.created_at.strftime("%Y-%m-%d %H:%M"),
                    fb.doctor.get_full_name() or fb.doctor.username,
                    fb.session_id,
                    fb.session.display_title,
                    fb.section,
                    fb.rating,
                    fb.comment,
                ])
            return response

        return render(request, self.template_name, {"feedback_list": feedback})


class LatencyLogView(LoginRequiredMixin, View):
    """Admin view: per-session pipeline timing breakdown.

    Shows audio duration, Modal transcription time, GPT-5 interpret time,
    GPT-5 SOAP generation time, and total — for every session that has
    timing data recorded in ScribeSession.timings.
    """

    template_name = "scribe/latency_log.html"

    def get(self, request):
        profile = DoctorProfile.objects.filter(user=request.user).first()
        is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
        if not is_admin:
            return redirect("scribe:record")

        sessions = (
            ScribeSession.objects
            .select_related("doctor")
            .exclude(timings={})
            .order_by("-created_at")[:100]
        )
        return render(request, self.template_name, {"sessions": sessions})


class ModalEndpointsView(LoginRequiredMixin, View):
    """Admin view: manage Modal Omni endpoint accounts (URL + API key cycling)."""

    template_name = "scribe/modal_endpoints.html"

    def _is_admin(self, request):
        profile = DoctorProfile.objects.filter(user=request.user).first()
        return (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser

    def get(self, request):
        if not self._is_admin(request):
            return redirect("scribe:record")
        endpoints = ModalOmniEndpoint.objects.all()
        return render(request, self.template_name, {"endpoints": endpoints})


@login_required
@require_POST
@csrf_protect
def modal_endpoint_add_api(request):
    """Add a new ModalOmniEndpoint (with optional pre-validation)."""
    profile = DoctorProfile.objects.filter(user=request.user).first()
    is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
    if not is_admin:
        return JsonResponse({"ok": False, "error": "Admin only"}, status=403)

    payload = _json_body(request)
    raw_url = (payload.get("base_url") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    label = (payload.get("label") or "").strip()
    priority = int(payload.get("priority") or 0)
    notes = (payload.get("notes") or "").strip()

    if not raw_url:
        return JsonResponse({"ok": False, "error": "base_url is required"}, status=400)
    if not api_key:
        return JsonResponse({"ok": False, "error": "api_key is required"}, status=400)

    # Normalise: strip any path so we always store just the origin.
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(raw_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if not base_url or base_url == "://":
        return JsonResponse({"ok": False, "error": "Invalid URL"}, status=400)

    ep = ModalOmniEndpoint.objects.create(
        label=label,
        base_url=base_url,
        api_key=api_key,
        priority=priority,
        notes=notes,
        status="active",
    )
    return JsonResponse({
        "ok": True,
        "id": ep.pk,
        "label": ep.label or ep.base_url,
        "base_url": ep.base_url,
        "status": ep.status,
    })


@login_required
@require_POST
@csrf_protect
def modal_endpoint_delete_api(request, pk):
    profile = DoctorProfile.objects.filter(user=request.user).first()
    is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
    if not is_admin:
        return JsonResponse({"ok": False, "error": "Admin only"}, status=403)
    ep = get_object_or_404(ModalOmniEndpoint, pk=pk)
    ep.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
@csrf_protect
def modal_endpoint_toggle_api(request, pk):
    """Toggle between active ↔ disabled, or re-activate an exhausted endpoint."""
    profile = DoctorProfile.objects.filter(user=request.user).first()
    is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
    if not is_admin:
        return JsonResponse({"ok": False, "error": "Admin only"}, status=403)
    ep = get_object_or_404(ModalOmniEndpoint, pk=pk)
    payload = _json_body(request)
    new_status = payload.get("status")
    if new_status not in {"active", "disabled", "exhausted"}:
        # If no explicit status, toggle active ↔ disabled (re-activate exhausted too)
        new_status = "disabled" if ep.status == "active" else "active"
    ep.status = new_status
    if new_status == "active":
        ep.exhausted_at = None
    ep.save(update_fields=["status", "exhausted_at"])
    return JsonResponse({"ok": True, "status": ep.status})


@login_required
@require_POST
@csrf_protect
def modal_endpoint_update_api(request, pk):
    """Edit an existing ModalOmniEndpoint's fields."""
    profile = DoctorProfile.objects.filter(user=request.user).first()
    is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
    if not is_admin:
        return JsonResponse({"ok": False, "error": "Admin only"}, status=403)
    ep = get_object_or_404(ModalOmniEndpoint, pk=pk)
    payload = _json_body(request)

    raw_url = (payload.get("base_url") or "").strip()
    if raw_url:
        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(raw_url)
        ep.base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    if "api_key" in payload and payload["api_key"].strip():
        ep.api_key = payload["api_key"].strip()
    if "label" in payload:
        ep.label = payload["label"].strip()
    if "priority" in payload:
        ep.priority = int(payload.get("priority") or 0)
    if "notes" in payload:
        ep.notes = payload["notes"].strip()

    ep.save()
    return JsonResponse({"ok": True})


@login_required
def modal_endpoint_validate_api(request):
    """GET/POST: hit the /health endpoint of a Modal URL + key and return result."""
    profile = DoctorProfile.objects.filter(user=request.user).first()
    is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
    if not is_admin:
        return JsonResponse({"ok": False, "error": "Admin only"}, status=403)

    if request.method == "POST":
        payload = _json_body(request)
    else:
        payload = request.GET

    raw_url = (payload.get("base_url") or "").strip()
    api_key = (payload.get("api_key") or "").strip()

    if not raw_url:
        return JsonResponse({"ok": False, "error": "base_url required"}, status=400)

    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(raw_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    health_url = base_url + "/health"

    try:
        import requests as _req
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key
        resp = _req.get(health_url, headers=headers, timeout=60)
        if resp.status_code == 401:
            return JsonResponse({"ok": False, "error": "Invalid API key (401)"})
        if not resp.ok:
            return JsonResponse({"ok": False, "error": f"HTTP {resp.status_code}"})
        data = resp.json()
        return JsonResponse({
            "ok": True,
            "base_url": base_url,
            "health": data,
        })
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"ok": False, "error": str(exc)})


class ComplianceView(LoginRequiredMixin, View):
    """Admin-only compliance dashboard summarising HIPAA/GDPR controls."""

    template_name = "scribe/compliance.html"

    def get(self, request):
        profile = DoctorProfile.objects.filter(user=request.user).first()
        is_admin = (profile and profile.is_admin) or request.user.is_staff or request.user.is_superuser
        if not is_admin:
            return redirect("scribe:record")

        from django.conf import settings as cfg
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=cfg.AUTO_DELETE_AUDIO_DAYS)
        purge_pending = (
            ScribeSession.objects
            .exclude(audio_file="")
            .filter(created_at__lt=cutoff)
            .count()
        )
        total_sessions = ScribeSession.objects.count()
        finalized_sessions = ScribeSession.objects.filter(status="finalized").count()
        total_doctors = DoctorProfile.objects.count()
        total_audit_events = SessionEvent.objects.count()

        return render(
            request,
            self.template_name,
            {
                "metrics": {
                    "total_sessions": total_sessions,
                    "finalized_sessions": finalized_sessions,
                    "total_doctors": total_doctors,
                    "total_audit_events": total_audit_events,
                    "purge_pending": purge_pending,
                    "auto_delete_days": cfg.AUTO_DELETE_AUDIO_DAYS,
                    "pilot_mode": cfg.PILOT_MODE,
                    "debug": cfg.DEBUG,
                },
                "controls": [
                    ("Cookies", "Secure + HttpOnly + SameSite, rolling 8h session lifetime"),
                    ("Headers", "X-Frame-Options DENY, no-sniff, strict referrer policy"),
                    ("Transport", "HSTS + SSL redirect when DEBUG is False"),
                    ("Auth", "Email-or-username login, role-based access (clinician/lead/admin)"),
                    ("Audit", "Every session create/edit/generate/export/finalize logged with actor"),
                    ("Retention", f"Audio auto-purge after {cfg.AUTO_DELETE_AUDIO_DAYS} days via management command"),
                    ("Encryption at rest", "TLS in transit; storage encryption depends on host (recommend disk-level)"),
                    ("PHI handling", "No patient names required; encounter IDs only during pilot"),
                    ("AI usage", "Drafts only; explicit 'review required before clinical use' on every note"),
                ],
            },
        )


class TriageView(LoginRequiredMixin, View):
    """Admin/staff sandbox for testing Patois ASR (MMS) + T5 rewrites locally."""

    template_name = "scribe/triage.html"

    def get(self, request):
        if not _triage_visible(request.user):
            return redirect("scribe:record")

        # Detect "no admin exists yet" so the page can offer one-click bootstrap.
        from accounts.views import _no_admins_exist
        return render(
            request,
            self.template_name,
            {
                "env": probe_environment(),
                "is_triage_admin": _triage_admin(request.user),
                "no_admins_exist": _no_admins_exist(),
                "default_system_prompt": (
                    ""
                  
                ),
            },
        )


class DrugCheckView(LoginRequiredMixin, View):
    """Drug interaction checker — Jamaican context.

    Open to all authenticated clinicians: this is a clinical decision-support
    feature, not a sandbox. AI advisory only — disclaimer is rendered into the
    UI and into every result.
    """

    template_name = "scribe/drug_check.html"

    def get(self, request):
        return render(request, self.template_name, {})


@login_required
def drug_search_api(request):
    """Autocomplete search across DrugAlias for the drug-check screen.

    GET /scribe/api/drug-search/?q=lis&limit=10
    Returns: { ok, results: [{label, generic, drug_class}] }
    Searches brand and generic with a starts-with first, then contains.
    """
    from .models import DrugAlias

    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"ok": True, "results": []})
    try:
        limit = max(1, min(20, int(request.GET.get("limit") or 12)))
    except ValueError:
        limit = 12

    from django.db.models import Q
    starts = (
        DrugAlias.objects
        .filter(Q(brand_name__istartswith=q) | Q(generic_name__istartswith=q))
        .order_by("-jamaican_common", "brand_name")[: limit * 2]
    )
    if starts.count() < limit:
        contains = (
            DrugAlias.objects
            .filter(Q(brand_name__icontains=q) | Q(generic_name__icontains=q))
            .exclude(pk__in=[d.pk for d in starts])
            .order_by("-jamaican_common", "brand_name")[: limit]
        )
        merged = list(starts) + list(contains)
    else:
        merged = list(starts)

    seen = set()
    results = []
    for d in merged:
        # Prefer the original brand for display, with generic + class hint.
        label = d.brand_name
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "label": label,
            "generic": d.generic_name,
            "drug_class": d.drug_class,
            "jamaican_common": d.jamaican_common,
        })
        # Also surface generic as its own row (so typing the generic finds it).
        gen_key = d.generic_name.lower()
        if gen_key not in seen and d.generic_name.lower() != d.brand_name.lower():
            seen.add(gen_key)
            results.append({
                "label": d.generic_name,
                "generic": d.generic_name,
                "drug_class": d.drug_class,
                "jamaican_common": d.jamaican_common,
            })
        if len(results) >= limit:
            break
    return JsonResponse({"ok": True, "results": results[:limit]})


# Common Jamaican / Caribbean herbal remedies + bush teas used in the
# drug-check screen autocomplete. Free text is still allowed; this is just
# a suggestion list so doctors don't have to spell unfamiliar names.
COMMON_HERBS = [
    "cerasee", "leaf of life (wonder of the world)", "fever grass (lemongrass)",
    "soursop leaf", "soursop bark", "ginger root", "moringa", "moringa leaf",
    "bissy (kola nut)", "lime bud", "guinea hen weed", "aloe vera (sinkle bible)",
    "noni", "neem", "comfrey", "annatto", "rosemary tea", "mint tea",
    "search me heart", "vervain", "blue vervain", "cannabis (ganja) tea",
    "dandelion", "sage tea", "thyme tea", "jackass bitters", "irish moss",
    "turmeric root", "peppermint tea", "christmas bush", "wild sage",
]


@login_required
def herb_search_api(request):
    """Simple substring filter over the common herbs list — no DB required."""
    q = (request.GET.get("q") or "").strip().lower()
    if len(q) < 2:
        return JsonResponse({"ok": True, "results": []})
    results = [{"label": h} for h in COMMON_HERBS if q in h.lower()][:12]
    return JsonResponse({"ok": True, "results": results})


@login_required
@require_POST
@csrf_protect
def drug_check_api(request):
    """Run an interaction check.

    Body:
        current_meds: list[str]   — whatever the doctor typed
        proposed_med: str         — drug being considered
        herbs: list[str]          — optional bush teas / herbal remedies
        patient_context: {age, sex, conditions[], allergies[]}
    """
    from .services.drug_check import check_interactions  # local: heavy import
    import time

    payload = _json_body(request)
    current = payload.get("current_meds") or []
    proposed = (payload.get("proposed_med") or "").strip()
    herbs = payload.get("herbs") or []
    context = payload.get("patient_context") or {}

    if not isinstance(current, list) or not isinstance(herbs, list):
        return JsonResponse({"ok": False, "error": "current_meds and herbs must be lists."}, status=400)
    if not proposed:
        return JsonResponse({"ok": False, "error": "proposed_med is required."}, status=400)

    started = time.perf_counter()
    try:
        result = check_interactions(
            current_meds=[str(x) for x in current],
            proposed_med=proposed,
            herbs=[str(x) for x in herbs],
            patient_context=context if isinstance(context, dict) else {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("drug check failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    duration_ms = int((time.perf_counter() - started) * 1000)

    # Audit row — keep verbatim for later safety review.
    try:
        from .models import DrugInteractionCheck
        DrugInteractionCheck.objects.create(
            doctor=request.user,
            inputs={
                "current_meds": current,
                "proposed_med": proposed,
                "herbs": herbs,
                "patient_context": context,
            },
            result=result,
            duration_ms=duration_ms,
            model_used=getattr(dj_settings, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "")[:120],
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not persist DrugInteractionCheck row")

    return JsonResponse({"ok": True, "result": result, "duration_ms": duration_ms})


@login_required
@require_POST
@csrf_protect
def triage_run_api(request):
    """Spawn a background Triage job and return its job_id immediately.

    Why background? MMS / Omni-ASR on CPU can take 30 s to several minutes
    (model load + inference) and would tie up the request thread + browser.
    The client polls /api/triage/jobs/<id>/ for progress.
    """
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    reap_old()

    backend = request.POST.get("backend", "mms")
    device = request.POST.get("device", dj_settings.TRIAGE_DEFAULT_DEVICE)
    target_lang = request.POST.get("target_lang", "jam")
    text_input = request.POST.get("text_input", "").strip()
    instruction = request.POST.get(
        "instruction",
        "Rewrite the following Jamaican Patois into clear clinical English.",
    )
    model_id = request.POST.get("model_id", "omniASR_CTC_1B")
    reference = request.POST.get("reference", "").strip()
    batch_size = max(1, int(request.POST.get("batch_size", "4") or "4"))
    gradio_url = request.POST.get("gradio_url", "").strip()
    audio = request.FILES.get("audio")

    saved_path = None
    if audio:
        from datetime import datetime
        stem = datetime.now().strftime("%Y%m%d-%H%M%S")
        ext = (audio.name.rsplit(".", 1)[-1] if "." in audio.name else "webm")[:5]
        saved_path = dj_settings.TRIAGE_AUDIO_DIR / f"{stem}-{request.user.pk}.{ext}"
        with open(saved_path, "wb") as fh:
            for chunk in audio.chunks():
                fh.write(chunk)

    if backend in ("mms", "omni", "parakeet") and not saved_path:
        return JsonResponse({"ok": False, "error": f"{backend} requires audio."}, status=400)

    def _run(job):
        _omni_result: dict | None = None
        try:
            if backend == "mms":
                job.stage = "loading MMS model (first run ≈ 60–120 s on CPU)…"
                job.stage = "transcribing with MMS…"
                raw = transcribe_mms(saved_path, device=device, target_lang=target_lang)
            elif backend == "omni":
                omni_lang = target_lang if "_" in target_lang else target_lang + "_Latn"
                if gradio_url:
                    job.stage = f"calling Gradio endpoint…"
                    _omni_result = transcribe_gradio(
                        saved_path,
                        gradio_url=gradio_url,
                        target_lang=omni_lang,
                        batch_size=batch_size,
                        reference=reference,
                    )
                else:
                    job.stage = f"loading {model_id} on {device}…"
                    _omni_result = transcribe_omni(
                        saved_path,
                        device=device,
                        model_card=model_id,
                        target_lang=omni_lang,
                        batch_size=batch_size,
                    )
                raw = _omni_result["text"]
            elif backend == "parakeet":
                job.stage = "loading Parakeet TDT 0.6B v2 (first run ≈ 2–5 min on CPU)…"
                job.stage = "transcribing with Parakeet…"
                raw = transcribe_parakeet(saved_path, device=device)
            elif backend == "t5_paraphrase":
                job.stage = "loading FLAN-T5…"
                raw = t5_rewrite(text_input, instruction=instruction, device=device)
            elif backend == "cloud_interpret":
                job.stage = "calling cloud LLM…"
                raw = run_interpret_patois(text_input or "")
            else:
                raise ValueError(f"Unknown backend '{backend}'.")
            job.result = {
                "raw_text": raw,
                "audio_saved_as": saved_path.name if saved_path else None,
            }
            if _omni_result:
                job.result["backend_meta"] = _omni_result
                if reference:
                    try:
                        job.result["accuracy"] = _compute_wer_cer(reference, raw)
                    except Exception as exc:  # noqa: BLE001
                        job.result["accuracy"] = {"error": str(exc)}
            job.stage = "done"
        except TriageDependencyError as exc:
            job.status = "error"
            job.error = str(exc)
        # Re-raise other exceptions so submit() catches them.

    job = submit_triage_job(backend, device, _run)
    return JsonResponse({"ok": True, "job_id": job.job_id})


@login_required
def triage_job_status_api(request, job_id):
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    job = get_triage_job(job_id)
    if job is None:
        return JsonResponse({"ok": False, "error": "Unknown job_id."}, status=404)
    return JsonResponse({"ok": True, "job": job.to_dict()})


@login_required
@require_POST
@csrf_protect
def triage_install_deps_api(request):
    """Run pip install for the Triage stack (transformers + torch + audio libs)
    in a background thread. ADMIN-ONLY — pip install is arbitrary code execution,
    must never be triggerable by a clinician even if Triage is generally visible.
    """
    if not _triage_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin only."}, status=403)

    payload = _json_body(request)
    profile = (request.POST.get("profile") if request.method == "POST" else None) or payload.get("profile", "cpu")

    pkgs_common = [
        "transformers",
        "accelerate",
        "librosa",
        "soundfile",
        "sentencepiece",
    ]
    if profile == "cuda":
        torch_args = [
            "torch",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cu121",
        ]
    else:
        torch_args = ["torch", "torchaudio"]

    import subprocess
    import sys
    import threading

    def _runner():
        cmd_torch = [sys.executable, "-m", "pip", "install", *torch_args]
        cmd_common = [sys.executable, "-m", "pip", "install", *pkgs_common]
        try:
            logger.info("triage install: %s", " ".join(cmd_torch))
            subprocess.run(cmd_torch, check=False, capture_output=True, text=True)
            logger.info("triage install: %s", " ".join(cmd_common))
            subprocess.run(cmd_common, check=False, capture_output=True, text=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("triage install failed: %s", exc)

    threading.Thread(target=_runner, daemon=True).start()
    return JsonResponse(
        {
            "ok": True,
            "started": True,
            "profile": profile,
            "note": (
                "Install started in the background. Refresh the page in a "
                "couple of minutes — the env probe will turn green when "
                "deps are ready. Then click 'Download MMS + T5 models'."
            ),
        }
    )


@login_required
@require_POST
@csrf_protect
def triage_install_audio_api(request):
    """Install denoise / diarization libraries into the active venv.

    target = 'denoise' | 'diarize' | 'all'. Admin only.
    """
    if not _triage_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin only."}, status=403)

    payload = _json_body(request)
    target = (payload.get("target") or "all").lower()

    pkg_groups = {
        "denoise": ["noisereduce", "deepfilternet"],
        "diarize": ["pyannote.audio"],
    }
    if target == "all":
        pkgs = pkg_groups["denoise"] + pkg_groups["diarize"]
    elif target in pkg_groups:
        pkgs = pkg_groups[target]
    else:
        return JsonResponse(
            {"ok": False, "error": f"Unknown target '{target}'."}, status=400
        )

    import subprocess
    import sys
    import threading

    def _runner():
        # Install one package at a time so a single failure doesn't abort
        # the others (e.g. deepfilternet wheel unavailable on Windows).
        for pkg in pkgs:
            cmd = [sys.executable, "-m", "pip", "install", pkg]
            try:
                logger.info("triage audio install: %s", " ".join(cmd))
                subprocess.run(cmd, check=False, capture_output=True, text=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("audio install failed for %s: %s", pkg, exc)

    threading.Thread(target=_runner, daemon=True).start()
    return JsonResponse(
        {
            "ok": True,
            "started": True,
            "target": target,
            "packages": pkgs,
            "note": (
                "Install started in the background. Toggle 'Denoise' or "
                "'Speaker diarization' on the next run once installed. "
                "noisereduce installs on every platform; DeepFilterNet "
                "requires Windows wheels — if it fails, denoise still "
                "works via noisereduce."
            ),
        }
    )


@login_required
@require_POST
@csrf_protect
def triage_download_api(request):
    """Trigger the model download in a background thread so the UI stays responsive.

    Status is observable by re-running probe_environment() (the page can poll).
    Note: this requires `transformers` to already be installed. If it isn't,
    we return a 503 with the pip command. ADMIN-ONLY.
    """
    if not _triage_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin only."}, status=403)

    payload = _json_body(request)
    target = payload.get("target", "all")  # all | mms | t5

    try:
        import transformers  # noqa: F401
    except ImportError:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "transformers is not installed. From a terminal, run:\n"
                    "  pip install transformers accelerate torch torchaudio "
                    "librosa soundfile sentencepiece"
                ),
            },
            status=503,
        )

    import threading
    from django.core.management import call_command

    def _runner():
        kwargs: dict = {}
        if target == "mms":
            kwargs["skip_t5"] = True
        elif target == "t5":
            kwargs["skip_mms"] = True
        try:
            call_command("download_triage_models", **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("download_triage_models failed: %s", exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return JsonResponse({"ok": True, "started": target})


@login_required
@csrf_protect
def triage_probe_api(request):
    """Return the current env probe so the UI can refresh without a full reload."""
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    return JsonResponse({"ok": True, "env": probe_environment()})


@login_required
@require_POST
@csrf_protect
@login_required
@require_POST
@csrf_protect
def triage_extract_demographics_api(request):
    """Pull patient + vitals from the conversation-mode clinical English text.

    Returns a strict JSON skeleton for an editable side-panel. Not persisted —
    the doctor uses it to verify what the transcript captured.
    """
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    payload = _json_body(request)
    text = (payload.get("text") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "No text provided."}, status=400)
    try:
        data = run_extract_demographics(text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("demographics extraction failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    return JsonResponse({"ok": True, "data": data})


def triage_interpret_api(request):
    """Interpret raw Patois text into clinical English.

    Accepts:
      text            — raw Patois transcript (required)
      interpreter     — 'azure' (default) or 'gemma_local'
      device          — 'cpu' | 'cuda' (Gemma only)
      gemma_model_id  — HuggingFace model id (default Qwen/Qwen3-1.7B; param
                        name kept for backwards compatibility — can pass any
                        instruction-tuned causal LM id)

    Both backends use the SAME PATOIS_INTERPRETER_SYSTEM_PROMPT so output
    shape is comparable — only the executor (cloud LLM vs local Gemma) changes.
    """
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    payload = _json_body(request)
    raw_text = (payload.get("text") or "").strip()
    if not raw_text:
        return JsonResponse({"ok": False, "error": "No text provided."}, status=400)

    interpreter = (payload.get("interpreter") or "azure").lower()
    device = (payload.get("device") or "cpu").lower()
    gemma_model_id = payload.get("gemma_model_id") or "Qwen/Qwen3-1.7B"

    import time
    started = time.perf_counter()
    try:
        if interpreter == "gemma_local":
            # Use the same Patois system prompt as Azure by importing it here.
            from .services.soap_generator import PATOIS_INTERPRETER_SYSTEM_PROMPT
            from .services.triage import gemma_interpret_patois
            # Inject the full Patois prompt into the user text — matches the
            # Azure-side trick that defeats the content filter.
            combined = (
                f"{PATOIS_INTERPRETER_SYSTEM_PROMPT.strip()}\n\n"
                f"=== END OF INSTRUCTIONS — PATOIS INPUT BELOW ===\n\n"
                f"PATWA TRANSCRIPT:\n{raw_text}"
            )
            clean = gemma_interpret_patois(
                combined, device=device, model_id=gemma_model_id
            )
        else:
            clean = run_interpret_patois(raw_text)
    except TriageDependencyError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    except Exception as exc:  # noqa: BLE001
        logger.exception("triage interpret failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return JsonResponse(
        {
            "ok": True,
            "clean_text": clean,
            "interpreter": interpreter,
            "device": device if interpreter == "gemma_local" else None,
            "duration_ms": elapsed_ms,
        }
    )


# ----- API views -----

def _demo_limit_block(request):
    """Return a JsonResponse if Test-mode caps this non-admin user, else None.

    In PlatformControl 'limited' mode a non-admin may create at most
    note_limit sessions. Gating session creation caps the whole pipeline
    (transcription + generation) per account during a public demo. Locked mode
    is handled globally by DemoLockdownMiddleware, so it isn't repeated here.
    """
    from accounts.models import PlatformControl, user_is_admin

    control = PlatformControl.get()
    if control.demo_mode != PlatformControl.MODE_LIMITED:
        return None
    if user_is_admin(request.user):
        return None
    used = ScribeSession.objects.filter(doctor=request.user).count()
    if used >= control.note_limit:
        return JsonResponse(
            {"ok": False, "error": control.message_for_mode(), "demo_limited": True},
            status=403,
        )
    return None


@login_required
@require_POST
@csrf_protect
def create_session_api(request):
    limited = _demo_limit_block(request)
    if limited is not None:
        return limited
    profile = _get_profile(request.user)
    audio = request.FILES.get("audio")
    note_format = request.POST.get("note_format", profile.default_note_style)
    length_mode = request.POST.get(
        "length_mode", "long_form" if profile.long_form_default else "normal"
    )
    title = request.POST.get("title", "").strip()
    chief_complaint = request.POST.get("chief_complaint", "").strip()
    transcript = request.POST.get("transcript", "").strip()
    duration_raw = request.POST.get("duration_seconds", "").strip()
    patient_name = request.POST.get("patient_name", "").strip()[:120]
    patient_identifier = request.POST.get("patient_identifier", "").strip()[:120]
    _pg_raw = request.POST.get("patient_gender", "").strip()[:1].upper()
    patient_gender = _pg_raw if _pg_raw in {"M", "F", "O"} else ""
    active_conditions = request.POST.get("active_conditions", "").strip()[:200]

    # Feature 1: if a persistent patient was selected, its record is
    # authoritative — overwrite the loose fields so the note uses the correct
    # name and sex (fixes inferred-demographics bug). No patient = quick session.
    patient_obj = _resolve_linked_patient(request.user, request.POST.get("patient_id"))
    if patient_obj is not None:
        patient_name = (patient_obj.full_name or patient_name)[:120]
        patient_gender = _EMR_SEX_TO_GENDER.get(patient_obj.sex, patient_gender)
        patient_identifier = (
            patient_obj.trn or patient_obj.nhf_card_number or patient_identifier
        )[:120]

    valid_formats = dict(ScribeSession.NOTE_FORMAT_CHOICES)
    valid_lengths = dict(ScribeSession.LENGTH_MODE_CHOICES)
    duration_seconds = int(duration_raw) if duration_raw.isdigit() else (0 if audio else None)

    try:
        session = ScribeSession.objects.create(
            doctor=request.user,
            title=title,
            chief_complaint=chief_complaint,
            patient_name=patient_name,
            patient_identifier=patient_identifier,
            patient_gender=patient_gender,
            active_conditions=active_conditions,
            note_format=note_format if note_format in valid_formats else "soap",
            length_mode=length_mode if length_mode in valid_lengths else "normal",
            session_type="text" if not audio else "dictation",
            transcript=transcript,
            status="draft",
            duration_seconds=duration_seconds,
            audio_file=audio if audio else None,
            patient=patient_obj,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Create session failed for doctor %s", request.user.pk)
        return JsonResponse(
            {"ok": False, "error": f"Could not create session: {exc}"},
            status=500,
        )
    _log(
        session,
        "created",
        f"format={session.note_format} length={session.length_mode}",
    )
    if audio:
        _log(session, "uploaded", f"size={audio.size} name={audio.name}")
    if request.POST.get("consent_acknowledged") in ("1", "true"):
        session.consent_acknowledged_at = timezone.now()
        session.save(update_fields=["consent_acknowledged_at"])
        audit_log.info(
            "session=%s doctor=%s event=consent_acknowledged ip=%s",
            session.pk, request.user.pk, request.META.get("REMOTE_ADDR", "unknown"),
        )
    return JsonResponse(
        {
            "ok": True,
            "session_id": session.pk,
            "has_audio": bool(audio),
            "transcript": session.transcript,
        }
    )


@login_required
@require_POST
@csrf_protect
def rename_session_api(request, pk):
    """PATCH patient_name on a session. Used by inline edit in history list."""
    import json as _json
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    try:
        body = _json.loads(request.body)
        name = str(body.get("patient_name", "")).strip()[:120]
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)
    session.patient_name = name
    session.save(update_fields=["patient_name", "updated_at"])
    return JsonResponse({"ok": True, "display_title": session.display_title})


@login_required
@require_POST
@csrf_protect
def transcribe_session_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if _scribe_billing_suspended(request.user):
        return JsonResponse({"ok": False, "error": _BILLING_BLOCK_MSG, "billing_suspended": True}, status=402)
    if not session.audio_file:
        return JsonResponse(
            {"ok": False, "error": "No audio attached to session."}, status=400
        )

    session.status = "transcribing"
    session.save(update_fields=["status", "updated_at"])
    try:
        if dj_settings.MODAL_OMNI_URL:
            _lang = getattr(getattr(request.user, "doctor_profile", None), "preferred_language", None) or "jam_Latn"
            resp = transcribe_modal_omni(str(session.audio_file.path), target_lang=_lang)
            transcript = resp.get("transcript", "")
        else:
            transcript = run_transcription(session.audio_file.path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcription failed for session %s", pk)
        session.status = "error"
        session.error_message = str(exc)
        session.save(update_fields=["status", "error_message", "updated_at"])
        _log(session, "error", f"transcription: {exc}")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    session.transcript = transcript
    # Preserve original ASR output so regeneration can re-run the interpreter.
    if not session.raw_transcript:
        session.raw_transcript = transcript
    session.status = "review"
    session.save(update_fields=["transcript", "raw_transcript", "status", "updated_at"])
    _log(session, "transcribed", f"chars={len(transcript)}")
    return JsonResponse({"ok": True, "transcript": transcript})


def _scribe_billing_suspended(user) -> bool:
    """True only when the user's clinic subscription is explicitly suspended.
    Gates AI note generation — never EMR record access."""
    try:
        from emr.services.access import get_membership
        return not get_membership(user).organisation.scribe_enabled
    except Exception:  # noqa: BLE001
        return False


_BILLING_BLOCK_MSG = (
    "AI note generation is paused for your clinic (subscription suspended). "
    "Patient records remain available — please contact your administrator."
)


@login_required
@require_POST
@csrf_protect
def generate_note_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if _scribe_billing_suspended(request.user):
        return JsonResponse({"ok": False, "error": _BILLING_BLOCK_MSG, "billing_suspended": True}, status=402)
    payload = _json_body(request)
    note_format = payload.get("note_format", session.note_format)
    length_mode = payload.get("length_mode", session.length_mode)
    force_reinterpret = _coerce_bool(payload.get("force_reinterpret", False))

    def _reconstruct_raw_from_step1(stored: str) -> str:
        m = re.search(
            r"STEP\s+1[^:]*:\s*\n+(.*?)(?=\n---|\nSTEP\s+2\b|\Z)",
            stored, re.DOTALL | re.IGNORECASE,
        )
        if not m:
            return ""
        tokens = []
        for line in m.group(1).splitlines():
            line = line.strip().lstrip("*- ")
            if " = " in line:
                tokens.append(line.split(" = ", 1)[0].strip())
        return " ".join(t for t in tokens if t)

    def _extract_step2(stored: str) -> str:
        m = re.search(
            r"STEP\s+2[^:]*:\s*\n+(.*?)(?=\n---|\nSTEP\s+3\b|\Z)",
            stored, re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    raw_source = session.raw_transcript
    if not raw_source and session.transcript:
        raw_source = _reconstruct_raw_from_step1(session.transcript)
        if raw_source:
            session.raw_transcript = raw_source
    # Ambient flow: raw ASR text arrives in the POST body because the background
    # transcription job doesn't persist it to the DB before generate is called.
    if not raw_source:
        body_transcript = (payload.get("transcript") or "").strip()
        if body_transcript:
            raw_source = body_transcript
            session.raw_transcript = body_transcript  # cache for future regeneration

    is_first_generation = not SOAPNote.objects.filter(session=session).exists()

    profile = _get_profile(request.user)
    _lang = getattr(profile, "preferred_language", None) or "jam_Latn"
    suggestive_assist = payload.get("suggestive_assist")
    if suggestive_assist is None:
        suggestive_assist = profile.suggestive_assist
    else:
        suggestive_assist = _coerce_bool(suggestive_assist)

    _gender_map = {"M": "Male", "F": "Female", "O": "Other"}
    _gender_label = _gender_map.get(session.patient_gender, "")
    _patient_ctx = f"Patient sex: {_gender_label}. Use correct pronouns throughout." if _gender_label else ""
    _custom = "\n".join(filter(None, [_patient_ctx, _nurse_vitals_context(session), profile.custom_instructions])).strip()

    use_combined = dj_settings.SCRIBE_COMBINED_PIPELINE and (is_first_generation or force_reinterpret) and raw_source
    result = None

    _t_pipeline_start = time.monotonic()
    _interpret_ms: int | None = None
    _generation_ms: int | None = None

    if use_combined:
        # Option 2: single GPT-5 call — interpret Patois + generate SOAP together.
        session.note_format = note_format
        session.length_mode = length_mode
        session.status = "generating"
        session.save(update_fields=["note_format", "length_mode", "status", "updated_at"])
        try:
            _t0 = time.monotonic()
            clinical_english, result = run_interpret_and_generate_soap(
                raw_source,
                note_format=note_format,
                specialty=profile.specialty,
                length_mode=length_mode,
                custom_instructions=_custom,
                custom_terms=profile.custom_terms,
                suggestive_assist=suggestive_assist,
                is_sensitive=session.is_sensitive,
            )
            # Combined: both phases in one call — store as generation_ms only
            _generation_ms = int((time.monotonic() - _t0) * 1000)
            transcript = clinical_english or raw_source
            session.transcript = transcript
            session.raw_transcript = session.raw_transcript or raw_source
        except Exception as exc:  # noqa: BLE001
            logger.exception("Combined pipeline failed for session %s; falling through to two-call path", pk)
            result = None  # fall through to two-call path below
            use_combined = False

    if not use_combined:
        # Two-call path (default): interpret first, then generate.
        if (is_first_generation or force_reinterpret) and raw_source:
            try:
                _t0 = time.monotonic()
                fresh = run_interpret_for_lang(raw_source, lang=_lang)
                _interpret_ms = int((time.monotonic() - _t0) * 1000)
                step2 = _extract_step2(fresh) or fresh.strip()
                # Interpreter returned nothing usable (content filter / model change)
                # — fall back to the raw ASR so we still have text to generate from.
                if not step2 or len(step2.strip()) < 5:
                    step2 = raw_source.strip()
                session.transcript = step2
                transcript = step2
            except Exception:  # noqa: BLE001
                # Interpreter (Azure) failed — don't lose the recording. Fall back
                # to the raw ASR text so note generation can still run on it,
                # rather than reporting a misleading "transcript empty" error.
                logger.exception("Interpret step failed for session %s; using raw transcript", pk)
                transcript = raw_source.strip() or (session.transcript or "").strip()
        else:
            # Regeneration: use cached Step 2 — no extra LLM call.
            transcript = (session.transcript or "").strip()
            if transcript and "STEP 2" in transcript.upper():
                step2 = _extract_step2(transcript)
                if step2:
                    transcript = step2
                    session.transcript = step2

        if not transcript or len(transcript.strip()) < 5:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Transcript came back empty. Try a longer recording or check your audio.",
                },
                status=400,
            )

        session.transcript = transcript
        session.note_format = note_format
        session.length_mode = length_mode
        session.status = "generating"
        session.save(update_fields=[
            "transcript", "note_format", "length_mode", "status", "updated_at"
        ])

        try:
            _t0 = time.monotonic()
            result = run_note_generation(
                transcript=transcript,
                note_format=note_format,
                specialty=profile.specialty,
                length_mode=length_mode,
                lang=_lang,
                custom_instructions=_custom,
                custom_terms=profile.custom_terms,
                suggestive_assist=suggestive_assist,
                is_sensitive=session.is_sensitive,
            )
            _generation_ms = int((time.monotonic() - _t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Note generation failed for session %s", pk)
            session.status = "error"
            session.error_message = str(exc)
            session.save(update_fields=["status", "error_message", "updated_at"])
            _log(session, "error", f"generate: {exc}")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    if not (result.full_note or "").strip():
        msg = (
            "The AI returned an empty note. This usually means the model spent "
            "its token budget on internal reasoning. Increase "
            "SCRIBE_MAX_COMPLETION_TOKENS in .env or switch to a non-reasoning deployment."
        )
        session.status = "error"
        session.error_message = msg
        session.save(update_fields=["status", "error_message", "updated_at"])
        _log(session, "error", "generate: empty output")
        return JsonResponse({"ok": False, "error": msg}, status=502)

    from .services.soap_generator import validate_note_safety  # local import
    safety_warnings = validate_note_safety(
        result.full_note,
        raw_transcript=session.raw_transcript or "",
    )
    all_flags = result.flags + safety_warnings

    note, _ = SOAPNote.objects.update_or_create(
        session=session,
        defaults={
            "visit_summary": result.visit_summary,
            "subjective": result.subjective,
            "objective": result.objective,
            "assessment": result.assessment,
            "plan": result.plan,
            "narrative": result.narrative,
            "full_note": result.full_note,
            "edited_note": result.full_note,
            "flags": all_flags,
        },
    )
    # Persist pipeline timings — merge into existing dict so transcription
    # timings (set during the ambient job) are not overwritten.
    _total_ms = int((time.monotonic() - _t_pipeline_start) * 1000)
    _new_timings: dict = {
        "pipeline_mode": "combined" if use_combined else "two-call",
        "generation_model": dj_settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT,
        "total_generation_ms": _total_ms,
    }
    if _interpret_ms is not None:
        _new_timings["interpret_ms"] = _interpret_ms
    if _generation_ms is not None:
        _new_timings["generation_ms"] = _generation_ms
    _merged_timings = dict(session.timings or {})
    _merged_timings.update(_new_timings)
    session.timings = _merged_timings

    session.status = "review"
    session.save(update_fields=["status", "transcript", "raw_transcript", "timings", "updated_at"])
    _log(session, "generated", f"format={result.note_format} flags={result.flags} interpret_ms={_interpret_ms} generation_ms={_generation_ms} total_ms={_total_ms}")

    return JsonResponse(
        {
            "ok": True,
            "session_id": session.pk,
            "note_format": result.note_format,
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
            "narrative": note.narrative,
            "full_note": note.full_note,
            "edited_note": note.edited_note,
            "flags": note.flags,
            "review_url": f"/scribe/sessions/{session.pk}/review/",
        }
    )


@login_required
@require_POST
@csrf_protect
def generate_note_stream_api(request, pk):
    """Option 3: stream SOAP generation tokens to the browser via SSE.

    Phase 1 (interpret) still blocks synchronously — streaming isn't possible
    there because we need the full output to extract Step 2.
    Phase 2 (SOAP generation) streams token-by-token so the doctor sees text
    appearing at ~2-3 s instead of waiting 15-20 s for the full response.

    Client POSTs the same body as generate_note_api, then reads the response
    body as a stream of SSE lines:
      data: {"stage": "interpreting"}
      data: {"stage": "generating"}
      data: {"chunk": "S:\nCC: ..."}   ← repeated as tokens arrive
      data: {"stage": "done", "session_id": 42, "review_url": "/scribe/..."}
      data: {"error": "..."}           ← on failure
    """
    from django.http import StreamingHttpResponse

    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if _scribe_billing_suspended(request.user):
        return JsonResponse({"ok": False, "error": _BILLING_BLOCK_MSG, "billing_suspended": True}, status=402)
    payload = _json_body(request)
    note_format = payload.get("note_format", session.note_format)
    length_mode = payload.get("length_mode", session.length_mode)
    force_reinterpret = _coerce_bool(payload.get("force_reinterpret", False))

    # --- resolve raw source (same logic as generate_note_api) ---
    def _extract_step2_local(stored: str) -> str:
        m = re.search(
            r"STEP\s+2[^:]*:\s*\n+(.*?)(?=\n---|\nSTEP\s+3\b|\Z)",
            stored, re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    raw_source = session.raw_transcript
    if not raw_source and session.transcript:
        raw_source = session.transcript
    if not raw_source:
        body_transcript = (payload.get("transcript") or "").strip()
        if body_transcript:
            raw_source = body_transcript
            session.raw_transcript = body_transcript

    is_first_generation = not SOAPNote.objects.filter(session=session).exists()

    profile = _get_profile(request.user)
    _lang = getattr(profile, "preferred_language", None) or "jam_Latn"
    suggestive_assist = payload.get("suggestive_assist")
    if suggestive_assist is None:
        suggestive_assist = profile.suggestive_assist
    else:
        suggestive_assist = _coerce_bool(suggestive_assist)

    _gender_map = {"M": "Male", "F": "Female", "O": "Other"}
    _gender_label = _gender_map.get(session.patient_gender, "")
    _patient_ctx = f"Patient sex: {_gender_label}. Use correct pronouns throughout." if _gender_label else ""
    _custom = "\n".join(filter(None, [_patient_ctx, _nurse_vitals_context(session), profile.custom_instructions])).strip()

    import json as _json

    def _event(data: dict) -> str:
        return f"data: {_json.dumps(data)}\n\n"

    def event_stream():
        transcript = (session.transcript or "").strip()

        # Phase 1 — interpretation (language-tier routed)
        if (is_first_generation or force_reinterpret) and raw_source:
            yield _event({"stage": "interpreting"})
            try:
                fresh = run_interpret_for_lang(raw_source, lang=_lang)
                step2 = _extract_step2_local(fresh) or fresh.strip()
                if not step2 or len(step2.strip()) < 5:
                    step2 = raw_source.strip()  # interpreter empty — use raw ASR
                transcript = step2
            except Exception:  # noqa: BLE001
                # Interpreter (Azure) failed — keep the recording usable by
                # generating from the raw ASR text instead of aborting.
                logger.exception("Stream interpret failed session %s; using raw transcript", pk)
                transcript = raw_source.strip()
            ScribeSession.objects.filter(pk=pk).update(
                transcript=transcript,
                raw_transcript=raw_source,
                note_format=note_format,
                length_mode=length_mode,
                status="generating",
            )
        else:
            # Cached transcript — skip interpret
            if transcript and "STEP 2" in transcript.upper():
                transcript = _extract_step2_local(transcript) or transcript
            ScribeSession.objects.filter(pk=pk).update(
                note_format=note_format,
                length_mode=length_mode,
                status="generating",
            )

        if not transcript or len(transcript.strip()) < 5:
            yield _event({"error": "Transcript came back empty. Try a longer recording or check your audio."})
            return

        # Phase 2 — Stream SOAP generation
        yield _event({"stage": "generating"})
        full_text = ""
        try:
            for chunk in run_stream_note_generation(
                transcript,
                note_format=note_format,
                specialty=profile.specialty,
                length_mode=length_mode,
                lang=_lang,
                custom_instructions=_custom,
                custom_terms=profile.custom_terms,
                suggestive_assist=suggestive_assist,
                is_sensitive=session.is_sensitive,
            ):
                full_text += chunk
                yield _event({"chunk": chunk})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Stream SOAP generation failed session %s", pk)
            ScribeSession.objects.filter(pk=pk).update(status="error", error_message=str(exc))
            yield _event({"error": str(exc)})
            return

        if not full_text.strip():
            msg = "The AI returned an empty note. Increase SCRIBE_MAX_COMPLETION_TOKENS in .env."
            ScribeSession.objects.filter(pk=pk).update(status="error", error_message=msg)
            yield _event({"error": msg})
            return

        # Post-process and save (same as generate_note_api)
        from .services.soap_generator import (  # noqa: PLC0415
            GeneratedNote,
            _extract_flags,
            _split_soap,
            _strip_ai_disclaimer,
            validate_note_safety,
        )
        full_text = _strip_ai_disclaimer(full_text)
        note_obj = GeneratedNote(note_format=note_format if note_format else "soap", full_note=full_text)
        note_obj.flags = _extract_flags(full_text)
        if note_obj.note_format == "soap":
            secs = _split_soap(full_text)
            note_obj.visit_summary = _strip_ai_disclaimer(secs["visit_summary"])
            note_obj.subjective = _strip_ai_disclaimer(secs["subjective"])
            note_obj.objective = _strip_ai_disclaimer(secs["objective"])
            note_obj.assessment = _strip_ai_disclaimer(secs["assessment"])
            note_obj.plan = _strip_ai_disclaimer(secs["plan"])

        safety_warnings = validate_note_safety(full_text, raw_transcript=raw_source or "")
        all_flags = note_obj.flags + safety_warnings

        SOAPNote.objects.update_or_create(
            session=session,
            defaults={
                "visit_summary": note_obj.visit_summary,
                "subjective": note_obj.subjective,
                "objective": note_obj.objective,
                "assessment": note_obj.assessment,
                "plan": note_obj.plan,
                "narrative": note_obj.narrative,
                "full_note": full_text,
                "edited_note": full_text,
                "flags": all_flags,
            },
        )
        ScribeSession.objects.filter(pk=pk).update(
            status="review",
            transcript=transcript,
            raw_transcript=raw_source or session.raw_transcript or "",
        )
        _log(session, "generated", f"stream format={note_obj.note_format} flags={all_flags}")
        yield _event({
            "stage": "done",
            "session_id": pk,
            "review_url": f"/scribe/sessions/{pk}/review/",
            "flags": all_flags,
        })

    response = StreamingHttpResponse(
        streaming_content=event_stream(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_POST
@csrf_protect
def save_note_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    # Hard server-side lock on finalized sessions — even if a client bypasses
    # the disabled inputs, we never mutate a reviewed clinical record.
    if session.status == "finalized":
        return JsonResponse(
            {"ok": False, "error": "Session is finalized and read-only."},
            status=409,
        )
    note = getattr(session, "note", None) or SOAPNote.objects.create(session=session)
    payload = _json_body(request)

    for field in ("visit_summary", "subjective", "objective", "assessment", "plan", "narrative", "edited_note"):
        if field in payload:
            setattr(note, field, payload[field] or "")

    if "body_markers" in payload and isinstance(payload["body_markers"], list):
        # Defensive: cap at 50 markers and strip any non-dict entries.
        # Whitelist the keys + truncate strings so we never write garbage.
        STR_KEYS = {
            "label": 80, "wound_type": 40, "duration": 80,
            "length_cm": 16, "width_cm": 16, "depth_cm": 16, "tracking_cm": 16,
            "tissue_necrotic": 8, "tissue_slough": 8, "tissue_granulating": 8,
            "tissue_epithelialising": 8, "tissue_hypergranulating": 8,
            "tissue_haematoma": 8, "tissue_bone_tendon": 8,
            "exudate": 24, "exudate_type": 32, "treatment_goal": 40,
            "analgesia": 16, "notes": 400,
            "date_added": 20, "referred_to": 120,
            # legacy fields from earlier marker shape
            "type": 40, "size_cm": 20,
        }
        LIST_KEYS = {"peri_wound": 12, "infection_signs": 12}
        cleaned = []
        for m in payload["body_markers"][:50]:
            if not isinstance(m, dict):
                continue
            row: dict = {
                "x": float(m.get("x", 0)),
                "y": float(m.get("y", 0)),
            }
            for k, limit in STR_KEYS.items():
                if k in m and m[k] is not None:
                    row[k] = str(m[k])[:limit]
            for k, max_items in LIST_KEYS.items():
                v = m.get(k)
                if isinstance(v, list):
                    row[k] = [str(x)[:40] for x in v[:max_items]]
            cleaned.append(row)
        note.body_markers = cleaned

    if "wound_chart" in payload and isinstance(payload["wound_chart"], dict):
        wc = payload["wound_chart"]
        factors = wc.get("factors_delaying_healing")
        chart_cleaned = {}
        if isinstance(factors, list):
            chart_cleaned["factors_delaying_healing"] = [str(f)[:40] for f in factors[:20]]
        if "allergies" in wc:
            chart_cleaned["allergies"] = str(wc.get("allergies") or "")[:240]
        note.wound_chart = chart_cleaned

    if "title" in payload:
        session.title = payload["title"][:160]
    if "chief_complaint" in payload:
        session.chief_complaint = payload["chief_complaint"][:200]
    if "patient_name" in payload:
        session.patient_name = (payload["patient_name"] or "")[:120]
    if "patient_identifier" in payload:
        session.patient_identifier = (payload["patient_identifier"] or "")[:120]
    if "patient_gender" in payload:
        valid_genders = {"", "M", "F", "O"}
        g = (payload["patient_gender"] or "")[:1].upper()
        session.patient_gender = g if g in valid_genders else ""
    if "active_conditions" in payload:
        session.active_conditions = (payload["active_conditions"] or "")[:200]
    if payload.get("consent_acknowledged") and not session.consent_acknowledged_at:
        session.consent_acknowledged_at = timezone.now()
        audit_log.info(
            "session=%s doctor=%s event=consent_acknowledged ip=%s",
            session.pk, session.doctor_id, request.META.get("REMOTE_ADDR", "unknown"),
        )
    if "is_sensitive" in payload:
        new_val = bool(payload["is_sensitive"])
        if new_val != session.is_sensitive:
            session.is_sensitive = new_val
            audit_log.info(
                "session=%s doctor=%s event=sensitive_flag_changed value=%s ip=%s",
                session.pk,
                session.doctor_id,
                new_val,
                request.META.get("REMOTE_ADDR", "unknown"),
            )

    note.save()
    session.save()
    _log(session, "edited", "doctor saved edits")
    return JsonResponse({"ok": True, "is_sensitive": session.is_sensitive})


@login_required
@require_POST
@csrf_protect
def rate_section_api(request, pk):
    """Record a thumbs-up or thumbs-down rating for a SOAP section.

    Body: { "section": "subjective"|"objective"|"assessment"|"plan"|"overall",
            "rating": "up"|"down",
            "comment": "optional free text" }
    Upserts so clicking thumbs-down twice just overwrites the previous rating.
    """
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    payload = _json_body(request)
    section = payload.get("section", "")
    rating = payload.get("rating", "")
    comment = (payload.get("comment") or "").strip()

    valid_sections = {c[0] for c in NoteFeedback.SECTION_CHOICES}
    valid_ratings = {c[0] for c in NoteFeedback.RATING_CHOICES}
    if section not in valid_sections or rating not in valid_ratings:
        return JsonResponse({"ok": False, "error": "Invalid section or rating."}, status=400)

    NoteFeedback.objects.update_or_create(
        session=session,
        doctor=request.user,
        section=section,
        defaults={"rating": rating, "comment": comment},
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
@csrf_protect
def finalize_session_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse(
            {"ok": False, "error": "No note to finalize yet."}, status=400
        )
    note.review_completed = True
    note.save(update_fields=["review_completed", "updated_at"])
    session.status = "finalized"
    session.finalized_at = timezone.now()
    session.save(update_fields=["status", "finalized_at", "updated_at"])
    _log(session, "finalized", "")

    # S3: finishing the note pops the patient off the doctor's waiting queue —
    # mark today's active appointment complete. Best-effort; never blocks finalize.
    if session.patient_id:
        try:
            from emr.models import Appointment
            Appointment.objects.filter(
                patient_id=session.patient_id,
                scheduled_for__date=timezone.localdate(),
                status__in=["checked_in", "triage", "with_doctor"],
            ).update(status="complete")
        except Exception:  # noqa: BLE001
            logger.exception("could not auto-complete appointment for session %s", pk)

        # F: auto-merge — populate the patient's encounter from this note so the
        # doctor never re-does it via "import from scribe". Best-effort.
        try:
            from emr.services.scribe_import import materialize_encounter_from_session
            materialize_encounter_from_session(session, request.user)
        except Exception:  # noqa: BLE001
            logger.exception("could not auto-materialize encounter for session %s", pk)

    return JsonResponse({"ok": True})


@login_required
@require_POST
@csrf_protect
def delete_session_api(request, pk):
    """Permanent session erasure — satisfies patient right to erasure under the DPA.

    Deletes the audio file from disk, the SOAPNote, all SessionEvents, and the
    ScribeSession row. Owner-only. Audit-logged. Cannot be undone.
    """
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    session_pk = session.pk
    session_repr = str(session)

    if session.audio_file:
        try:
            session.audio_file.delete(save=False)
        except Exception:
            pass

    session.delete()  # cascades to SOAPNote, SessionEvents, NoteShares

    audit_log.info(
        "session=%s doctor=%s event=session_deleted name=%r ip=%s",
        session_pk,
        request.user.pk,
        session_repr,
        request.META.get("REMOTE_ADDR", "unknown"),
    )
    return JsonResponse({"ok": True, "redirect": "/scribe/sessions/"})


@login_required
@require_POST
@csrf_protect
def suggest_improvements_api(request, pk):
    """Run an AI quality pass over the current note. Returns markdown bullets."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse({"ok": False, "error": "Generate a note first."}, status=400)
    profile = _get_profile(request.user)
    note_text = note.edited_note or note.full_note or note.narrative or ""
    try:
        suggestions = run_suggest_improvements(note_text, specialty=profile.specialty)
    except Exception as exc:  # noqa: BLE001
        logger.exception("suggest_improvements failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    _log(session, "edited", "ai-suggestions requested")
    return JsonResponse({"ok": True, "suggestions": suggestions})


@login_required
@require_POST
@csrf_protect
def polish_note_api(request, pk):
    """Run a grammar/clarity pass over the current note. Updates the note in place."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse({"ok": False, "error": "Generate a note first."}, status=400)
    source = note.edited_note or note.full_note or note.narrative or ""
    if not source.strip():
        return JsonResponse({"ok": False, "error": "Note is empty."}, status=400)
    try:
        polished = run_polish_grammar(source)
    except Exception as exc:  # noqa: BLE001
        logger.exception("polish_grammar failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    note.edited_note = polished
    # If we have S/O/A/P sections in polished output, update the structured fields.
    from .services.soap_generator import _split_soap  # local import
    sections = _split_soap(polished)
    if any(sections.values()):
        note.visit_summary = sections["visit_summary"]
        note.subjective = sections["subjective"]
        note.objective = sections["objective"]
        note.assessment = sections["assessment"]
        note.plan = sections["plan"]
    note.save()
    _log(session, "edited", "polish-grammar applied")
    return JsonResponse(
        {
            "ok": True,
            "edited_note": note.edited_note,
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
        }
    )


@require_POST
@csrf_protect
def magic_edit_api(request, pk):
    """Apply a doctor-supplied instruction to the current note via AI."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if session.status == "finalized":
        return JsonResponse({"ok": False, "error": "Session is finalized."}, status=403)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse({"ok": False, "error": "Generate a note first."}, status=400)
    payload = _json_body(request)
    instruction = (payload.get("instruction") or "").strip()
    if not instruction:
        return JsonResponse({"ok": False, "error": "Instruction is required."}, status=400)
    source = note.edited_note or note.full_note or note.narrative or ""
    if not source.strip():
        return JsonResponse({"ok": False, "error": "Note is empty."}, status=400)
    try:
        from .services.pipeline import run_magic_edit
        result = run_magic_edit(source, instruction)
    except Exception as exc:  # noqa: BLE001
        logger.exception("magic_edit failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    note.edited_note = result
    from .services.soap_generator import _split_soap
    sections = _split_soap(result)
    if any(sections.values()):
        note.visit_summary = sections["visit_summary"]
        note.subjective = sections["subjective"]
        note.objective = sections["objective"]
        note.assessment = sections["assessment"]
        note.plan = sections["plan"]
    note.save()
    _log(session, "edited", "magic-edit: " + instruction[:80])
    return JsonResponse({
        "ok": True,
        "edited_note": note.edited_note,
        "subjective": note.subjective,
        "objective": note.objective,
        "assessment": note.assessment,
        "plan": note.plan,
    })


@login_required
@require_POST
@csrf_protect
def quick_transcribe_api(request):
    """Transcribe a short audio blob (quick-edit dictation). Returns text only."""
    if _scribe_billing_suspended(request.user):
        return JsonResponse({"ok": False, "error": _BILLING_BLOCK_MSG, "billing_suspended": True}, status=402)
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"ok": False, "error": "No audio sent."}, status=400)
    # Persist to a temp file the SDK can read.
    import os
    import tempfile

    suffix = ".webm" if audio.name.endswith(".webm") else os.path.splitext(audio.name)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in audio.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        text = run_transcription(tmp_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Quick transcribe failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JsonResponse({"ok": True, "transcript": (text or "").strip()})


@login_required
@require_POST
@csrf_protect
def resume_session_api(request, pk):
    """Transcribe a new audio blob, append it to the session transcript, return the combined text."""
    import os
    import tempfile

    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"ok": False, "error": "No audio sent."}, status=400)

    suffix = ".webm" if audio.name.endswith(".webm") else os.path.splitext(audio.name)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in audio.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        new_text = run_transcription(tmp_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resume transcription failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    new_text = (new_text or "").strip()
    existing = (session.transcript or "").strip()
    combined = (existing + "\n\n" + new_text).strip() if existing else new_text
    session.transcript = combined
    session.status = "review"
    session.save(update_fields=["transcript", "status", "updated_at"])
    _log(session, "resumed", f"appended_chars={len(new_text)}")
    return JsonResponse({"ok": True, "transcript": combined})


@login_required
@require_POST
@csrf_protect
def share_note_api(request, pk):
    """Issue a 30-min authenticated claim token for the QR → PC transfer flow.

    No patient data leaves the server.  The QR code points to /scribe/claim/<token>/
    which requires the SAME authenticated user — scanning on the phone tells the
    PC browser to navigate to this session via SSE.  WhatsApp sharing has been
    removed as it transmitted PHI outside the platform.
    """
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if session.is_sensitive:
        audit_log.info(
            "session=%s doctor=%s event=share_blocked_sensitive ip=%s",
            session.pk,
            session.doctor_id,
            request.META.get("REMOTE_ADDR", "unknown"),
        )
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "This session is marked as sensitive. Transfer is disabled "
                    "to protect the patient's data."
                ),
            },
            status=403,
        )

    token, expires_at = make_share_token()
    NoteShare.objects.create(session=session, token=token, expires_at=expires_at)
    _log(session, "exported", "QR claim token issued")

    # The claim URL requires authentication — no patient data in the QR itself
    claim_url = request.build_absolute_uri(f"/scribe/claim/{token}/")

    return JsonResponse(
        {
            "ok": True,
            "claim_url": claim_url,
            "qr_data_url": qr_data_url(claim_url),
            "expires_at": expires_at.isoformat(),
            "session_id": session.pk,
        }
    )


@login_required
def share_view(request, token):
    """Authenticated view of a shared note (legacy share URL).

    Now requires the viewing user to be the session's doctor — public
    note URLs have been removed as a data-protection measure.
    """
    share = get_object_or_404(NoteShare, token=token)
    if share.session.doctor != request.user:
        return render(request, "scribe/claim_wrong_account.html", status=403)
    if not share.is_valid():
        return render(request, "scribe/share_expired.html", status=410)
    share.opened_count += 1
    share.save(update_fields=["opened_count"])
    note = getattr(share.session, "note", None)
    return render(request, "scribe/share.html", {"session": share.session, "note": note})


@login_required
def phone_claim_view(request, token):
    """Phone landing page after scanning the QR code.

    Validates the token belongs to the current user, fires an SSE event to the
    PC browser, and shows a confirmation page.  No patient data is rendered here.
    """
    share = get_object_or_404(NoteShare, token=token)
    if share.session.doctor != request.user:
        return render(request, "scribe/claim_wrong_account.html", status=403)
    if not share.is_valid():
        return render(request, "scribe/share_expired.html", status=410)

    share.opened_count += 1
    share.save(update_fields=["opened_count"])
    _fire_scan_event(request.user.pk, share.session.pk)
    return render(request, "scribe/phone_claim_success.html", {"session": share.session})


# ── SSE scan event infrastructure ────────────────────────────────────────────
# Each PC browser holds an open SSE connection; phone scans fire events into
# a per-user slot.  Single-process in-memory dict — adequate for the pilot.

import threading as _threading
import time as _time

_scan_lock = _threading.Lock()
# {user_id: {"session_id": int, "at": float}}
_pending_scans: dict[int, dict] = {}


def _fire_scan_event(user_id: int, session_pk: int) -> None:
    with _scan_lock:
        _pending_scans[user_id] = {"session_id": session_pk, "at": _time.monotonic()}


@login_required
def scan_events_view(request):
    """SSE stream — PC browser listens here for phone-scan events.

    The generator polls the in-memory _pending_scans dict.  When a phone claim
    fires, the PC receives {"event":"scan","session_id":42} and navigates to
    that session with a glow highlight.  Connection auto-expires after 3 minutes;
    the browser reconnects via standard SSE retry.
    """
    import json as _json
    from django.http import StreamingHttpResponse

    user_id = request.user.pk
    last_seen: float = _time.monotonic()

    def event_stream():
        nonlocal last_seen
        yield "data: {\"event\": \"connected\"}\n\n"
        deadline = _time.monotonic() + 180  # 3-min window; browser will reconnect
        while _time.monotonic() < deadline:
            with _scan_lock:
                pending = _pending_scans.get(user_id)
            if pending and pending["at"] > last_seen:
                last_seen = pending["at"]
                yield f"data: {_json.dumps({'event': 'scan', 'session_id': pending['session_id']})}\n\n"
                with _scan_lock:
                    if _pending_scans.get(user_id) is pending:
                        _pending_scans.pop(user_id, None)
            _time.sleep(0.8)
            yield ": hb\n\n"  # SSE comment keeps connection alive through proxies

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# In-memory ownership map for ambient jobs: job_id -> user.pk
# Single-process only; adequate for the pilot. Swap for DB or cache at scale.
_AMBIENT_JOB_OWNERS: dict[str, int] = {}


@login_required
@require_POST
@csrf_protect
def ambient_transcribe_api(request, pk):
    """Start an async MMS transcription job for the session's audio.

    Returns {ok: true, job_id: ...}. Client polls /api/ambient-jobs/<job_id>/
    until status == 'done', then calls /api/sessions/<pk>/generate/ with the
    resulting transcript.
    """
    if _scribe_billing_suspended(request.user):
        return JsonResponse({"ok": False, "error": _BILLING_BLOCK_MSG, "billing_suspended": True}, status=402)
    try:
        session = ScribeSession.objects.get(pk=pk, doctor=request.user)
    except ScribeSession.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Session not found."}, status=404)

    if not session.audio_file:
        return JsonResponse(
            {"ok": False, "error": "No audio attached to this session."},
            status=400,
        )

    audio_path = session.audio_file.path
    payload = _json_body(request)

    # TEMPORARY: allow UI toggle to override env default for latency testing.
    # Remove the payload override once testing is done; keep only the env default.
    backend = payload.get("backend") or dj_settings.AMBIENT_BACKEND  # "modal" | "local"

    def _run(job):
        if backend == "modal-omni":
            job.stage = "sending to Modal omniASR GPU…"
            _lang = getattr(getattr(request.user, "doctor_profile", None), "preferred_language", None) or "jam_Latn"
            resp = transcribe_modal_omni(str(audio_path), target_lang=_lang)
            raw_text = resp.get("transcript", "")
            job.result = {
                "raw_text": raw_text,
                "session_id": pk,
                "backend": "modal-omni",
                "audio_seconds": resp.get("audio_seconds"),
                "chunk_count": resp.get("chunk_count"),
                "load_ms": resp.get("load_ms"),
                "preprocessing_ms": resp.get("preprocessing_ms"),
                "inference_ms": resp.get("inference_ms"),
                "total_ms": resp.get("total_ms"),
                "realtime_factor": resp.get("realtime_factor"),
                "model_device": resp.get("device", "cuda"),
            }
        elif backend == "modal":
            job.stage = "sending to Modal MMS GPU…"
            resp = transcribe_modal_mms(str(audio_path), target_lang="jam")
            raw_text = resp.get("transcript", "")
            job.result = {
                "raw_text": raw_text,
                "session_id": pk,
                "backend": "modal",
                "audio_seconds": resp.get("audio_seconds"),
                "preprocessing_ms": resp.get("preprocessing_ms"),
                "inference_ms": resp.get("inference_ms"),
                "total_ms": resp.get("total_ms"),
                "realtime_factor": resp.get("realtime_factor"),
                "model_device": resp.get("device", "cuda"),
            }
        else:
            job.stage = "loading MMS model (first run ≈ 60–120 s on CPU)…"
            job.stage = "transcribing with MMS…"
            raw_text = transcribe_mms(str(audio_path), device="cpu", target_lang="jam")
            job.result = {"raw_text": raw_text, "session_id": pk, "backend": "local"}
        # Persist raw ASR output + timing data to DB.
        update_fields: dict = {}
        if raw_text:
            update_fields["raw_transcript"] = raw_text
        # Store transcription timings from Modal response so the latency log
        # and review page can show audio_seconds, transcription RTT, etc.
        transcription_timings: dict = {}
        result = job.result or {}
        for key in ("audio_seconds", "preprocessing_ms", "inference_ms", "total_ms", "realtime_factor"):
            if result.get(key) is not None:
                transcription_timings[key] = result[key]
        if transcription_timings:
            # Use F-expression-safe approach: read then update to avoid race.
            existing = ScribeSession.objects.filter(pk=pk).values_list("timings", flat=True).first() or {}
            existing.update(transcription_timings)
            update_fields["timings"] = existing
        if update_fields:
            ScribeSession.objects.filter(pk=pk).update(**update_fields)
        job.stage = "done"

    job = submit_triage_job(f"asr-ambient-{backend}", "gpu" if backend != "local" else "cpu", _run)
    _AMBIENT_JOB_OWNERS[job.job_id] = request.user.pk
    return JsonResponse({"ok": True, "job_id": job.job_id})


def ambient_job_api(request, job_id):
    """Poll status of an ambient transcription job (no triage-admin gate)."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Not authenticated."}, status=401)
    if _AMBIENT_JOB_OWNERS.get(job_id) != request.user.pk:
        return JsonResponse({"ok": False, "error": "Not found."}, status=404)
    job = get_triage_job(job_id)
    if job is None:
        return JsonResponse({"ok": False, "error": "Unknown job."}, status=404)
    return JsonResponse({"ok": True, "job": job.to_dict()})


@login_required
@require_POST
@csrf_protect
def update_preferences_api(request):
    profile = _get_profile(request.user)
    payload = _json_body(request)

    if payload.get("theme") in {"light", "dark", "auto"}:
        profile.theme = payload["theme"]
    if "font_scale" in payload:
        try:
            scale = max(80, min(160, int(payload["font_scale"])))
            profile.font_scale = scale
        except (TypeError, ValueError):
            pass
    if payload.get("default_note_style") in {"soap", "narrative", "chart"}:
        profile.default_note_style = payload["default_note_style"]
    if "long_form_default" in payload:
        profile.long_form_default = bool(payload["long_form_default"])
    if "suggestive_assist" in payload:
        profile.suggestive_assist = _coerce_bool(payload["suggestive_assist"])
    if payload.get("specialty") in dict(DoctorProfile.SPECIALTY_CHOICES):
        profile.specialty = payload["specialty"]
    if payload.get("preferred_language") in dict(DoctorProfile.LANGUAGE_CHOICES):
        profile.preferred_language = payload["preferred_language"]
    if "custom_instructions" in payload:
        profile.custom_instructions = (payload["custom_instructions"] or "").strip()

    profile.save()
    return JsonResponse(
        {
            "ok": True,
            "theme": profile.theme,
            "font_scale": profile.font_scale,
            "default_note_style": profile.default_note_style,
            "long_form_default": profile.long_form_default,
            "suggestive_assist": profile.suggestive_assist,
            "specialty": profile.specialty,
            "preferred_language": profile.preferred_language,
            "custom_instructions": profile.custom_instructions,
        }
    )
