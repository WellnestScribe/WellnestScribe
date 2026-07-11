"""Views for the modular EMR app."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

logger = logging.getLogger(__name__)

from scribe.models import ScribeSession

from .forms import (
    AllergyForm,
    AppointmentForm,
    EncounterForm,
    OrganisationForm,
    PatientForm,
    ReferralForm,
    VitalForm,
    common_code_catalog,
    common_drug_catalog,
    diagnosis_formset_class,
    medication_formset_class,
)
from .models import (
    Appointment,
    Encounter,
    OrganisationMembership,
    Patient,
    Referral,
    Vital,
)
from .services.access import membership_for_request, user_choices_for_organisation
from .services.audit import log_audit_event
from .services.search import (
    active_medications_for_patient,
    active_problem_list_for_patient,
    search_patients,
)
from .services.scribe_import import build_scribe_import_bundle


def _base_context(request):
    emr = membership_for_request(request)
    return {
        "emr_organisation": emr.organisation,
        "emr_membership": emr.membership,
    }


def _require(predicate, request, message_text: str):
    emr = membership_for_request(request)
    if predicate(emr.membership):
        return emr
    messages.error(request, message_text)
    return None


def _scribe_queryset_for_user(user):
    return ScribeSession.objects.filter(
        doctor=user,
        status__in=["review", "finalized"],
    ).order_by("-created_at")


def _prefill_patient_from_scribe(session: ScribeSession) -> dict:
    raw = (session.patient_name or "").strip()
    first = ""
    last = ""
    if raw:
        bits = raw.split()
        if len(bits) == 1:
            first = bits[0]
        else:
            first = bits[0]
            last = " ".join(bits[1:])
    return {
        "legal_first_name": first,
        "legal_last_name": last,
        "preferred_name": raw,
    }


def _form_has_meaningful_data(cleaned_data: dict) -> bool:
    return any(
        value not in (None, "", [], {}, ())
        for key, value in cleaned_data.items()
        if key not in {"DELETE", "id"}
    )


def _save_encounter_children(
    *,
    encounter: Encounter,
    organisation,
    patient,
    request,
    diagnosis_formset,
    medication_formset,
):
    # save(commit=False) must run BEFORE .deleted_objects is populated.
    diagnoses = diagnosis_formset.save(commit=False)
    for obj in diagnosis_formset.deleted_objects:
        obj.delete()
    for diagnosis in diagnoses:
        diagnosis.organisation = organisation
        diagnosis.patient = patient
        diagnosis.encounter = encounter
        diagnosis.diagnosing_provider = request.user
        diagnosis.save()

    medications = medication_formset.save(commit=False)
    for obj in medication_formset.deleted_objects:
        obj.delete()
    for medication in medications:
        medication.organisation = organisation
        medication.patient = patient
        medication.encounter = encounter
        medication.prescribing_provider = request.user
        medication.save()


@login_required
def dashboard_view(request):
    emr = membership_for_request(request)
    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    all_appts = list(
        Appointment.objects.filter(
            organisation=emr.organisation,
            scheduled_for__range=(day_start, day_end),
        ).select_related("patient")
    )

    # Active (still waiting) sorted FIFO get positions 1..N and float to the top;
    # completed/cancelled drop below with no position. This is what makes "who's
    # next" obvious and stops everyone showing "Queue 1".
    active_statuses = ("checked_in", "triage", "with_doctor")
    active = sorted(
        [a for a in all_appts if a.status in active_statuses],
        key=lambda a: (a.queue_number or 9999, a.scheduled_for),
    )
    for i, a in enumerate(active, start=1):
        a.queue_position = i
    inactive = sorted(
        [a for a in all_appts if a.status not in active_statuses],
        key=lambda a: a.scheduled_for,
    )
    for a in inactive:
        a.queue_position = None
    appointments = active + inactive

    stats = {
        "today": len(all_appts),
        "checked_in": sum(1 for a in all_appts if a.status == "checked_in"),
        "triage": sum(1 for a in all_appts if a.status == "triage"),
        "with_doctor": sum(1 for a in all_appts if a.status == "with_doctor"),
        "complete": sum(1 for a in all_appts if a.status == "complete"),
        "patients": Patient.objects.filter(organisation=emr.organisation).count(),
    }

    recent_patients = (
        Patient.objects.filter(organisation=emr.organisation)
        .annotate(last_encounter=Max("encounters__encounter_date"))
        .order_by("-last_encounter", "-updated_at")[:6]
    )

    return render(
        request,
        "emr/dashboard.html",
        {
            **_base_context(request),
            "appointments": appointments,
            "stats": stats,
            "recent_patients": recent_patients,
            "today": today,
        },
    )


@login_required
@require_http_methods(["GET"])
def waiting_queue_api(request):
    """JSON: today's 'patients to come' for the doctor's record screen.

    Digital version of the docket pile in the doctor's office. Returns
    appointments the nurse has checked in / triaged (excludes complete and
    cancelled=left), ordered by queue position, with a vitals snapshot so the
    doctor can read the docket at a glance. Polled by the record page, so any
    nurse change (reorder, patient left, new arrival, vitals) reflects within
    seconds. No AI - plain DB reads.
    """
    emr = membership_for_request(request)
    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    appts = (
        Appointment.objects.filter(
            organisation=emr.organisation,
            scheduled_for__range=(day_start, day_end),
            status__in=["checked_in", "triage", "with_doctor"],
        )
        .select_related("patient")
        .order_by("queue_number", "scheduled_for")
    )

    queue = []
    for a in appts:
        p = a.patient
        vital = (
            Vital.objects.filter(patient=p, recorded_at__range=(day_start, day_end))
            .order_by("-recorded_at")
            .first()
        )
        vitals = {}
        vitals_full = []
        if vital:
            if vital.bp_systolic and vital.bp_diastolic:
                vitals["bp"] = f"{vital.bp_systolic}/{vital.bp_diastolic}"
            if vital.weight_kg:
                vitals["weight"] = f"{vital.weight_kg} kg"
            if vital.blood_glucose_mmol:
                vitals["glucose"] = f"{vital.blood_glucose_mmol} mmol/L"
            if vital.temperature_celsius:
                vitals["temp"] = f"{vital.temperature_celsius}°C"
            for label, val in [
                ("Blood pressure", f"{vital.bp_systolic}/{vital.bp_diastolic} mmHg" if vital.bp_systolic and vital.bp_diastolic else None),
                ("Pulse", f"{vital.pulse_bpm} bpm" if vital.pulse_bpm else None),
                ("Temperature", f"{vital.temperature_celsius} °C" if vital.temperature_celsius else None),
                ("Respiratory rate", f"{vital.respiratory_rate}/min" if vital.respiratory_rate else None),
                ("SpO₂", f"{vital.oxygen_saturation}%" if vital.oxygen_saturation else None),
                ("Blood glucose", f"{vital.blood_glucose_mmol} mmol/L" if vital.blood_glucose_mmol else None),
                ("Weight", f"{vital.weight_kg} kg" if vital.weight_kg else None),
                ("Height", f"{vital.height_cm} cm" if vital.height_cm else None),
                ("Pain score", f"{vital.pain_score}/10" if vital.pain_score is not None else None),
            ]:
                if val:
                    vitals_full.append({"label": label, "value": val})
        queue.append({
            "position": len(queue) + 1,
            "appointment_id": a.pk,
            "patient_id": p.pk,
            "name": p.display_name,
            "mrn": p.mrn,
            "age": p.age_display,
            "sex": p.get_sex_display(),
            "status": a.status,
            "status_label": a.get_status_display(),
            "queue_number": a.queue_number,
            "scheduled_for": a.scheduled_for.isoformat(),
            "complaint": (a.notes or "")[:80],
            "has_vitals": bool(vitals),
            "vitals": vitals,
            "vitals_full": vitals_full,
            "record_url": f"{reverse('scribe:record')}?patient={p.pk}",
            "chart_url": reverse("emr:patient_detail", args=[p.pk]),
        })

    return JsonResponse({"queue": queue, "count": len(queue)})


@login_required
@require_http_methods(["GET"])
def patient_search_api(request):
    """JSON patient search over real emr.Patient records.

    Shared by the Register-page dedupe banner and the record modal. Returns
    docket-style fields (MRN + DOB + age + community) so same-name patients are
    distinguishable. Scoped to the user's organisation. No AI.
    """
    emr = membership_for_request(request)
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"patients": []})

    results = list(search_patients(emr.organisation, q)[:10])
    patients = [{
        "id": p.pk,
        "name": p.display_name,
        "mrn": p.mrn,
        "dob": p.date_of_birth.strftime("%Y-%m-%d") if p.date_of_birth else "",
        "age": p.age_display,
        "sex": p.get_sex_display(),
        "community": p.community or p.parish or "",
        "trn": p.trn or "",
        "visits": p.scribe_sessions.count(),
        "chart_url": reverse("emr:patient_detail", args=[p.pk]),
        "record_url": f"{reverse('scribe:record')}?patient={p.pk}",
    } for p in results]
    return JsonResponse({"patients": patients})


@login_required
def patient_search_view(request):
    from datetime import date, timedelta
    from django.db.models import Q

    emr = membership_for_request(request)
    org = emr.organisation
    term = request.GET.get("q", "").strip()

    # ── "Who was here?" date filter ──────────────────────────────────────────
    seen = request.GET.get("seen", "").strip()
    today = timezone.localdate()
    date_from = date_to = None
    seen_label = ""
    seen_date = ""  # ISO date when a specific day was picked (not a preset)
    if seen == "today":
        date_from = date_to = today
        seen_label = "today"
    elif seen == "yesterday":
        date_from = date_to = today - timedelta(days=1)
        seen_label = "yesterday"
    elif seen == "7":
        date_from, date_to, seen_label = today - timedelta(days=6), today, "the last 7 days"
    elif seen == "30":
        date_from, date_to, seen_label = today - timedelta(days=29), today, "the last 30 days"
    elif seen:
        try:
            d = date.fromisoformat(seen)
            date_from = date_to = d
            seen_label = d.strftime("%b %d, %Y")
            seen_date = seen
        except ValueError:
            seen = ""

    if date_from is not None:
        # Patients with an encounter or appointment in the window = "were here".
        enc_ids = Encounter.objects.filter(
            organisation=org, encounter_date__range=(date_from, date_to)
        ).values_list("patient_id", flat=True)
        appt_ids = Appointment.objects.filter(
            organisation=org, scheduled_for__date__range=(date_from, date_to)
        ).values_list("patient_id", flat=True)
        ids = set(enc_ids) | set(appt_ids)
        qs = Patient.objects.filter(organisation=org, pk__in=ids)
        if term:
            qs = qs.filter(
                Q(legal_first_name__icontains=term)
                | Q(legal_last_name__icontains=term)
                | Q(preferred_name__icontains=term)
                | Q(nhf_card_number__icontains=term)
                | Q(trn__icontains=term)
                | Q(phone_primary__icontains=term)
            )
        patients = list(qs.order_by("legal_last_name", "legal_first_name")[:200])
    elif term:
        patients = list(search_patients(org, term)[:100])
    else:
        # No filters → browse all patients (capped) so the list is usable.
        patients = list(
            Patient.objects.filter(organisation=org)
            .order_by("legal_last_name", "legal_first_name")[:50]
        )

    total = Patient.objects.filter(organisation=org).count()

    return render(
        request,
        "emr/patient_search.html",
        {
            **_base_context(request),
            "query": term,
            "patients": patients,
            "patient_total": total,
            "seen": seen,
            "seen_label": seen_label,
            "seen_date": seen_date,
            "scribe_session_id": request.GET.get("scribe", "").strip(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_create_view(request):
    emr = _require(
        lambda membership: membership.can_register_patients(),
        request,
        "Your role cannot register patients.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    scribe_session = None
    initial = {}
    scribe_id = request.GET.get("scribe") or request.POST.get("scribe")
    if scribe_id:
        scribe_session = get_object_or_404(_scribe_queryset_for_user(request.user), pk=scribe_id)
        initial.update(_prefill_patient_from_scribe(scribe_session))

    form = PatientForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        patient = form.save(commit=False)
        patient.organisation = emr.organisation
        patient.created_by = request.user
        patient.updated_by = request.user
        patient.save()
        log_audit_event(
            request,
            emr.organisation,
            action="create",
            resource_type="patient",
            resource_id=patient.pk,
            detail=f"Registered patient {patient.display_name}",
        )
        messages.success(request, "Patient registered.")
        if scribe_session is not None:
            # Close the loop: link the scribe session to this new patient so the
            # note appears under the patient's Scribe-visits history (Feature 1).
            scribe_session.patient = patient
            scribe_session.save(update_fields=["patient"])
            return redirect(f"{reverse('emr:encounter_create', args=[patient.pk])}?scribe={scribe_session.pk}")
        return redirect("emr:patient_detail", pk=patient.pk)

    return render(
        request,
        "emr/patient_form.html",
        {
            **_base_context(request),
            "form": form,
            "mode": "create",
            "patient": None,
            "scribe_session": scribe_session,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_edit_view(request, pk):
    emr = _require(
        lambda membership: membership.can_register_patients(),
        request,
        "Your role cannot update patient demographics.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    patient = get_object_or_404(Patient, pk=pk, organisation=emr.organisation)
    form = PatientForm(request.POST or None, instance=patient)
    if request.method == "POST" and form.is_valid():
        patient = form.save(commit=False)
        patient.updated_by = request.user
        patient.save()
        log_audit_event(
            request,
            emr.organisation,
            action="update",
            resource_type="patient",
            resource_id=patient.pk,
            detail=f"Updated demographics for {patient.display_name}",
        )
        messages.success(request, "Patient details updated.")
        return redirect("emr:patient_detail", pk=patient.pk)

    return render(
        request,
        "emr/patient_form.html",
        {
            **_base_context(request),
            "form": form,
            "mode": "edit",
            "patient": patient,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_detail_view(request, pk):
    emr = membership_for_request(request)
    patient = get_object_or_404(Patient, pk=pk, organisation=emr.organisation)

    allergy_form = AllergyForm(request.POST or None, prefix="allergy")
    if request.method == "POST":
        if not emr.membership.can_register_patients():
            return HttpResponseForbidden("Your role cannot update allergies.")
        if allergy_form.is_valid():
            allergy = allergy_form.save(commit=False)
            allergy.organisation = emr.organisation
            allergy.patient = patient
            allergy.save()
            log_audit_event(
                request,
                emr.organisation,
                action="create",
                resource_type="allergy",
                resource_id=allergy.pk,
                detail=f"Added allergy {allergy.allergen_name} for {patient.display_name}",
            )
            messages.success(request, "Allergy saved.")
            return redirect("emr:patient_detail", pk=patient.pk)

    log_audit_event(
        request,
        emr.organisation,
        action="view",
        resource_type="patient",
        resource_id=patient.pk,
        detail=f"Viewed patient chart for {patient.display_name}",
    )

    recent_encounters = patient.encounters.select_related("provider").order_by("-encounter_date", "-created_at")[:8]
    upcoming_appointments = patient.appointments.filter(status__in=["scheduled", "checked_in", "triage", "with_doctor"]).order_by("scheduled_for")[:6]
    active_medications = active_medications_for_patient(patient)[:8]
    problem_list = active_problem_list_for_patient(patient)[:8]
    last_vitals = patient.vitals.order_by("-recorded_at").first()
    recent_scribe_sessions = _scribe_queryset_for_user(request.user)[:6]
    # Feature 1: this patient's own scribe visits (sessions linked via FK).
    patient_visits = (
        patient.scribe_sessions.select_related("note").order_by("-created_at")[:20]
    )

    return render(
        request,
        "emr/patient_detail.html",
        {
            **_base_context(request),
            "patient": patient,
            "recent_encounters": recent_encounters,
            "upcoming_appointments": upcoming_appointments,
            "active_medications": active_medications,
            "problem_list": problem_list,
            "last_vitals": last_vitals,
            "allergy_form": allergy_form,
            "recent_scribe_sessions": recent_scribe_sessions,
            "patient_visits": patient_visits,
        },
    )


@login_required
@require_http_methods(["GET"])
def patient_activity_api(request, patient_pk):
    """Lightweight signature of a patient's encounters + scribe visits so the
    chart can auto-refresh when new activity lands (e.g. a note just finalized)."""
    emr = membership_for_request(request)
    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    enc = list(patient.encounters.order_by("-created_at").values_list("pk", "encounter_status")[:12])
    vis = list(
        ScribeSession.objects.filter(patient=patient).order_by("-created_at").values_list("pk", "status")[:12]
    )
    return JsonResponse({"sig": f"{enc}|{vis}"})


@login_required
@require_http_methods(["GET", "POST"])
def appointment_create_view(request, patient_pk):
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot manage the worklist.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    form = AppointmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.organisation = emr.organisation
        appointment.patient = patient
        appointment.created_by = request.user
        appointment.save()
        log_audit_event(
            request,
            emr.organisation,
            action="create",
            resource_type="appointment",
            resource_id=appointment.pk,
            detail=f"Scheduled {patient.display_name} for {appointment.scheduled_for:%Y-%m-%d %H:%M}",
        )
        messages.success(request, "Patient added to the worklist.")
        return redirect("emr:patient_detail", pk=patient.pk)

    return render(
        request,
        "emr/appointment_form.html",
        {
            **_base_context(request),
            "form": form,
            "patient": patient,
        },
    )


@login_required
@require_POST
def appointment_status_view(request, pk):
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot update the worklist.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    appointment = get_object_or_404(Appointment, pk=pk, organisation=emr.organisation)
    next_status = request.POST.get("status", "").strip()
    valid_statuses = {choice[0] for choice in Appointment._meta.get_field("status").choices}
    if next_status not in valid_statuses:
        messages.error(request, "Unknown appointment status.")
        return redirect(request.POST.get("next") or "emr:dashboard")
    appointment.status = next_status
    reason = (request.POST.get("reason") or "").strip()[:120]
    fields = ["status", "updated_at"]
    # Guardrail: taking a patient OUT of the queue records why, so nobody is
    # silently dropped and left waiting.
    if reason and next_status == "cancelled":
        appointment.notes = ((appointment.notes + " · ") if appointment.notes else "") + f"Removed: {reason}"
        fields.append("notes")
    appointment.save(update_fields=fields)
    log_audit_event(
        request,
        emr.organisation,
        action="update",
        resource_type="appointment",
        resource_id=appointment.pk,
        detail=f"Moved {appointment.patient.display_name} to {next_status}"
        + (f" ({reason})" if reason else ""),
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "status": next_status})
    messages.success(request, "Worklist updated.")
    return redirect(request.POST.get("next") or reverse("emr:dashboard"))


@login_required
@require_POST
def appointment_delete_view(request, pk):
    """Remove a worklist entry permanently (the clinical note/encounter is kept)."""
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot manage the worklist.",
    )
    if emr is None:
        return redirect("emr:dashboard")
    appointment = get_object_or_404(Appointment, pk=pk, organisation=emr.organisation)
    name = appointment.patient.display_name
    appointment.delete()
    log_audit_event(
        request, emr.organisation, action="delete", resource_type="appointment",
        resource_id=pk, detail=f"Removed {name} from the worklist",
    )
    messages.success(request, f"{name} removed from the worklist.")
    return redirect("emr:dashboard")


@login_required
@require_POST
def worklist_close_day_view(request):
    """End-of-day: mark every still-waiting patient complete so tomorrow starts clean."""
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot manage the worklist.",
    )
    if emr is None:
        return redirect("emr:dashboard")
    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    n = Appointment.objects.filter(
        organisation=emr.organisation,
        scheduled_for__range=(day_start, day_end),
        status__in=["scheduled", "checked_in", "triage", "with_doctor"],
    ).update(status="complete")
    log_audit_event(
        request, emr.organisation, action="update", resource_type="worklist",
        resource_id="", detail=f"Closed worklist for the day ({n} cleared)",
    )
    messages.success(request, f"Worklist saved for the day - {n} patient(s) cleared from the queue.")
    return redirect("emr:dashboard")


@login_required
@require_POST
def appointment_reorder_view(request, pk):
    """Nurse reorders the waiting queue (move a patient up/down).

    Normalises today's waiting appointments to 1..N by current order, then
    swaps the target with its neighbour. The doctor's record-screen poll picks
    up the new order within seconds - no push needed.
    """
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot reorder the worklist.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    appointment = get_object_or_404(Appointment, pk=pk, organisation=emr.organisation)
    direction = request.POST.get("direction", "")
    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))

    siblings = list(
        Appointment.objects.filter(
            organisation=emr.organisation,
            scheduled_for__range=(day_start, day_end),
            status__in=["checked_in", "triage", "with_doctor"],
        ).order_by("queue_number", "scheduled_for")
    )
    # Normalise queue positions so swapping is always well-defined.
    for i, s in enumerate(siblings, start=1):
        if s.queue_number != i:
            s.queue_number = i
            s.save(update_fields=["queue_number", "updated_at"])

    idx = next((i for i, s in enumerate(siblings) if s.pk == appointment.pk), None)
    if idx is not None:
        swap = idx - 1 if direction == "up" else idx + 1
        if 0 <= swap < len(siblings):
            a, b = siblings[idx], siblings[swap]
            a.queue_number, b.queue_number = b.queue_number, a.queue_number
            a.save(update_fields=["queue_number", "updated_at"])
            b.save(update_fields=["queue_number", "updated_at"])

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect(request.POST.get("next") or reverse("emr:dashboard"))


# ── Appointments calendar (T1) ───────────────────────────────────────────────
def _parse_appt_dt(raw):
    """Parse a FullCalendar / booking datetime string to an aware datetime."""
    if not raw:
        return None
    from django.utils.dateparse import parse_date, parse_datetime
    dt = parse_datetime(raw)
    if dt is None:
        d = parse_date(raw)
        if d is not None:
            dt = datetime.combine(d, datetime.min.time())
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@login_required
def appointments_calendar_view(request):
    """Full-page calendar: click a slot -> search a patient -> book them in."""
    emr = membership_for_request(request)
    return render(request, "emr/appointments.html", {
        **_base_context(request),
        "encounter_type_choices": Encounter._meta.get_field("encounter_type").choices,
        "can_manage": emr.membership.can_manage_schedule(),
    })


@login_required
def appointments_feed_api(request):
    """FullCalendar event feed for the clinic, filtered to the requested range."""
    emr = membership_for_request(request)
    qs = Appointment.objects.filter(organisation=emr.organisation).select_related("patient")
    start = _parse_appt_dt(request.GET.get("start"))
    end = _parse_appt_dt(request.GET.get("end"))
    if start:
        qs = qs.filter(scheduled_for__gte=start)
    if end:
        qs = qs.filter(scheduled_for__lte=end)
    colours = {
        "scheduled": "#0c7ec2", "checked_in": "#16a34a", "triage": "#f59e0b",
        "with_doctor": "#7c3aed", "complete": "#64748b", "cancelled": "#ef4444",
    }
    events = []
    for a in qs.order_by("scheduled_for")[:1000]:
        events.append({
            "id": a.pk,
            "title": a.patient.display_name,
            "start": a.scheduled_for.isoformat(),
            "color": colours.get(a.status, "#0c7ec2"),
            "extendedProps": {
                "patient_id": a.patient_id,
                "phone": a.patient.phone_primary or "",
                "mrn": a.patient.mrn,
                "status": a.status,
                "status_label": a.get_status_display(),
                "type": a.get_encounter_type_display(),
                "notes": a.notes or "",
                "time": a.scheduled_for.strftime("%b %d, %Y at %I:%M %p"),
                "chart_url": reverse("emr:patient_detail", args=[a.patient_id]),
                "triage_url": reverse("emr:triage", args=[a.pk]),
            },
        })
    return JsonResponse({"events": events})


@login_required
@require_POST
def appointment_book_api(request):
    """Create an appointment from the calendar (patient + datetime + type)."""
    emr = _require(lambda m: m.can_manage_schedule(), request, "Your role cannot manage the schedule.")
    if emr is None:
        return JsonResponse({"ok": False, "error": "Your role cannot manage the schedule."}, status=403)
    patient = get_object_or_404(Patient, pk=request.POST.get("patient_id"), organisation=emr.organisation)
    when = _parse_appt_dt(request.POST.get("scheduled_for"))
    if when is None:
        return JsonResponse({"ok": False, "error": "Pick a valid date and time."}, status=400)
    etype = request.POST.get("encounter_type") or "acute"
    valid_types = {c[0] for c in Encounter._meta.get_field("encounter_type").choices}
    if etype not in valid_types:
        etype = "acute"
    appt = Appointment.objects.create(
        organisation=emr.organisation, patient=patient, scheduled_for=when,
        encounter_type=etype, status="scheduled",
        notes=(request.POST.get("notes") or "")[:500], created_by=request.user,
    )
    log_audit_event(
        request, emr.organisation, action="create", resource_type="appointment",
        resource_id=appt.pk, detail=f"Booked {patient.display_name} for {when:%Y-%m-%d %H:%M}",
    )
    return JsonResponse({"ok": True, "id": appt.pk})


@login_required
def appointments_due_api(request):
    """Count of today's upcoming (not-yet-seen) appointments - sidebar bubble."""
    emr = membership_for_request(request)
    today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    n = Appointment.objects.filter(
        organisation=emr.organisation,
        scheduled_for__range=(day_start, day_end),
        status__in=["scheduled", "checked_in"],
    ).count()
    return JsonResponse({"due": n})


@login_required
@require_http_methods(["GET", "POST"])
def triage_view(request, appointment_pk):
    emr = _require(
        lambda membership: membership.can_record_vitals(),
        request,
        "Your role cannot record vitals.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    appointment = get_object_or_404(Appointment, pk=appointment_pk, organisation=emr.organisation)
    encounter = appointment.encounters.order_by("-created_at").first()
    vital_instance = getattr(encounter, "vitals", None) if encounter else None
    if vital_instance is None:
        vital_instance = Vital(organisation=emr.organisation, patient=appointment.patient)

    form = VitalForm(request.POST or None, instance=vital_instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            encounter_to_use = encounter
            if encounter_to_use is None:
                encounter_to_use = Encounter.objects.create(
                    organisation=emr.organisation,
                    patient=appointment.patient,
                    appointment=appointment,
                    provider=request.user if emr.membership.is_doctor else None,
                    encounter_date=timezone.localdate(),
                    encounter_type=appointment.encounter_type,
                    chief_complaint=appointment.notes,
                    created_by=request.user,
                    updated_by=request.user,
                )
            vital = form.save(commit=False)
            vital.organisation = emr.organisation
            vital.patient = appointment.patient
            vital.encounter = encounter_to_use
            vital.recorded_by = request.user
            vital.save()
            appointment.status = "with_doctor"
            appointment.save(update_fields=["status", "updated_at"])

        log_audit_event(
            request,
            emr.organisation,
            action="update",
            resource_type="vitals",
            resource_id=vital.pk,
            detail=f"Recorded vitals for {appointment.patient.display_name}",
        )
        messages.success(request, "Vitals saved.")
        return redirect("emr:encounter_edit", patient_pk=appointment.patient.pk, encounter_pk=encounter_to_use.pk)

    return render(
        request,
        "emr/triage_form.html",
        {
            **_base_context(request),
            "appointment": appointment,
            "form": form,
            "patient": appointment.patient,
            "encounter": encounter,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def encounter_create_view(request, patient_pk):
    return _encounter_editor(request, patient_pk=patient_pk, encounter_pk=None)


@login_required
@require_http_methods(["GET", "POST"])
def encounter_edit_view(request, patient_pk, encounter_pk):
    return _encounter_editor(request, patient_pk=patient_pk, encounter_pk=encounter_pk)


@login_required
@require_http_methods(["GET"])
def encounter_view(request, patient_pk, encounter_pk):
    """Read-only view of a past encounter - full clinical detail, no editing.

    Anyone in the clinic can open it (org-scoped); the editable Advanced editor
    stays behind can_edit_encounters, so nurses/pharmacists can read a chart
    without being able to change it.
    """
    emr = membership_for_request(request)
    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    encounter = get_object_or_404(
        Encounter.objects.select_related("provider", "signed_by", "scribe_session"),
        pk=encounter_pk,
        patient=patient,
        organisation=emr.organisation,
    )
    log_audit_event(
        request,
        emr.organisation,
        action="view",
        resource_type="encounter",
        resource_id=encounter.pk,
        detail=f"Viewed encounter {encounter.pk} for {patient.display_name}",
    )
    note_sections = [
        ("Chief complaint", encounter.chief_complaint),
        ("History of presenting illness", encounter.history_of_presenting_illness),
        ("Review of systems", encounter.review_of_systems),
        ("Physical examination", encounter.physical_examination),
        ("Assessment", encounter.assessment_notes),
        ("Plan", encounter.plan_notes),
    ]
    return render(
        request,
        "emr/encounter_view.html",
        {
            **_base_context(request),
            "patient": patient,
            "encounter": encounter,
            "note_sections": note_sections,
            "vitals": getattr(encounter, "vitals", None),
            "diagnoses": encounter.diagnoses.all(),
            "medications": encounter.medications.all(),
            "addenda": encounter.addenda.select_related("author").all(),
            "can_edit": emr.membership.can_edit_encounters(),
        },
    )


def _encounter_editor(request, *, patient_pk, encounter_pk=None):
    emr = _require(
        lambda membership: membership.can_edit_encounters(),
        request,
        "Your role cannot document encounters.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    is_new = encounter_pk is None
    encounter = None
    if encounter_pk is not None:
        encounter = get_object_or_404(
            Encounter,
            pk=encounter_pk,
            patient=patient,
            organisation=emr.organisation,
        )
    else:
        encounter = Encounter(
            organisation=emr.organisation,
            patient=patient,
            provider=request.user if emr.membership.is_doctor else None,
            encounter_date=timezone.localdate(),
            created_by=request.user,
            updated_by=request.user,
        )

    if encounter.encounter_status == "signed" and request.method == "POST":
        messages.error(request, "Signed encounters are read-only.")
        return redirect("emr:encounter_edit", patient_pk=patient.pk, encounter_pk=encounter.pk)

    scribe_id = request.GET.get("scribe") or request.POST.get("scribe_id")
    scribe_session = None
    initial = {}
    scribe_import = None
    if is_new and scribe_id:
        scribe_session = get_object_or_404(_scribe_queryset_for_user(request.user), pk=scribe_id)
        scribe_import = build_scribe_import_bundle(
            scribe_session,
            encounter_date=encounter.encounter_date,
        )
        initial.update(scribe_import.encounter_initial)

    provider_queryset = user_choices_for_organisation(emr.organisation)
    # Scope the Scribe-session picker to THIS patient's linked notes (Feature 1),
    # not every session the doctor ever recorded. Include the note being
    # imported via ?scribe= even if it isn't linked to the patient yet.
    from django.db.models import Q
    scribe_queryset = _scribe_queryset_for_user(request.user).filter(patient=patient)
    if scribe_session is not None:
        scribe_queryset = _scribe_queryset_for_user(request.user).filter(
            Q(patient=patient) | Q(pk=scribe_session.pk)
        )
    form = EncounterForm(
        request.POST or None,
        instance=encounter,
        initial=initial,
        organisation=emr.organisation,
        provider_queryset=provider_queryset,
        scribe_queryset=scribe_queryset,
        prefix="encounter",
    )
    form.fields["appointment"].queryset = patient.appointments.order_by("-scheduled_for")

    vital_instance = getattr(encounter, "vitals", None) if encounter.pk else None
    if vital_instance is None:
        vital_instance = Vital(organisation=emr.organisation, patient=patient)
    vitals_initial = scribe_import.vitals_initial if request.method != "POST" and scribe_import else None
    vitals_form = VitalForm(
        request.POST or None,
        instance=vital_instance,
        prefix="vitals",
        initial=vitals_initial,
    )

    diagnosis_initial = scribe_import.diagnosis_initial if request.method != "POST" and scribe_import else None
    medication_initial = scribe_import.medication_initial if request.method != "POST" and scribe_import else None

    diagnosis_formset = diagnosis_formset_class(
        extra_forms=len(diagnosis_initial or []),
    )(
        request.POST or None,
        instance=encounter,
        prefix="diagnosis",
        initial=diagnosis_initial,
    )
    medication_formset = medication_formset_class(
        extra_forms=len(medication_initial or []),
    )(
        request.POST or None,
        instance=encounter,
        prefix="medication",
        initial=medication_initial,
    )

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "sign" and not emr.membership.can_sign_encounters():
            messages.error(request, "Only doctor roles can sign an encounter. Your changes will be saved as a draft.")
            action = "save"
        if form.is_valid() and vitals_form.is_valid() and diagnosis_formset.is_valid() and medication_formset.is_valid():
            with transaction.atomic():
                encounter = form.save(commit=False)
                encounter.organisation = emr.organisation
                encounter.patient = patient
                encounter.updated_by = request.user
                if encounter.created_by_id is None:
                    encounter.created_by = request.user
                if encounter.provider_id is None and emr.membership.is_doctor:
                    encounter.provider = request.user
                if action == "sign":
                    encounter.encounter_status = "signed"
                    encounter.signed_by = request.user
                    encounter.signed_at = timezone.now()
                encounter.save()

                vital = vitals_form.save(commit=False)
                if _form_has_meaningful_data(vitals_form.cleaned_data):
                    vital.organisation = emr.organisation
                    vital.patient = patient
                    vital.encounter = encounter
                    vital.recorded_by = request.user
                    vital.save()

                _save_encounter_children(
                    encounter=encounter,
                    organisation=emr.organisation,
                    patient=patient,
                    request=request,
                    diagnosis_formset=diagnosis_formset,
                    medication_formset=medication_formset,
                )

                appointment = encounter.appointment
                if appointment is not None:
                    appointment.status = "complete" if encounter.encounter_status == "signed" else "with_doctor"
                    appointment.save(update_fields=["status", "updated_at"])

            log_audit_event(
                request,
                emr.organisation,
                action="sign" if action == "sign" else ("create" if is_new else "update"),
                resource_type="encounter",
                resource_id=encounter.pk,
                detail=f"{'Signed' if action == 'sign' else 'Saved'} encounter for {patient.display_name}",
            )
            messages.success(
                request,
                "Encounter signed." if action == "sign" else "Encounter saved.",
            )
            return redirect("emr:encounter_edit", patient_pk=patient.pk, encounter_pk=encounter.pk)

    log_audit_event(
        request,
        emr.organisation,
        action="view",
        resource_type="encounter" if encounter.pk else "encounter_draft",
        resource_id=encounter.pk or "",
        detail=f"Opened encounter editor for {patient.display_name}",
    )

    return render(
        request,
        "emr/encounter_form.html",
        {
            **_base_context(request),
            "patient": patient,
            "encounter": encounter,
            "form": form,
            "vitals_form": vitals_form,
            "diagnosis_formset": diagnosis_formset,
            "medication_formset": medication_formset,
            "icd10_catalog": common_code_catalog(),
            "drug_catalog": common_drug_catalog(),
            "current_medications": active_medications_for_patient(patient)[:8],
            "problem_list": active_problem_list_for_patient(patient)[:8],
            "allergies": patient.allergies.filter(status="active"),
            "last_vitals": patient.vitals.order_by("-recorded_at").first(),
            "scribe_session": scribe_session,
            "scribe_import": scribe_import,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def intake_view(request, patient_pk):
    """Nurse intake: capture chief complaint + vitals, then send to the queue.

    Deliberately light - the nurse does NOT do ROS / physical exam / signing.
    On submit it puts the patient in the doctor's waiting queue (today's
    appointment → 'triage') with the vitals attached, exactly like the paper
    docket flow: weigh, take BP, jot the complaint, hand to the doctor.
    """
    emr = _require(
        lambda membership: membership.can_record_vitals(),
        request,
        "Your role cannot record vitals.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    today = timezone.localdate()
    # If already in today's queue, this is an EDIT of the same intake (not a new
    # one): pre-load the existing appointment, vitals and complaint so nothing
    # is duplicated. Intake + Vitals are one screen now.
    active_appt = (
        Appointment.objects.filter(
            organisation=emr.organisation, patient=patient,
            scheduled_for__date=today,
            status__in=["scheduled", "checked_in", "triage", "with_doctor"],
        ).order_by("scheduled_for").first()
    )
    existing_vital = (
        Vital.objects.filter(patient=patient, recorded_at__date=today)
        .order_by("-recorded_at").first()
    )
    existing_encounter = active_appt.encounters.order_by("-created_at").first() if active_appt else None
    vitals_form = VitalForm(request.POST or None, prefix="vitals", instance=existing_vital)

    if request.method == "POST" and vitals_form.is_valid():
        chief = (request.POST.get("chief_complaint") or "").strip()
        enc_type = (request.POST.get("encounter_type") or "acute").strip()
        valid_types = {c[0] for c in Encounter._meta.get_field("encounter_type").choices}
        if enc_type not in valid_types:
            enc_type = "acute"
        with transaction.atomic():
            appt = active_appt
            if appt is None:
                next_q = (
                    Appointment.objects.filter(
                        organisation=emr.organisation, scheduled_for__date=today
                    ).aggregate(m=Max("queue_number"))["m"] or 0
                ) + 1
                appt = Appointment.objects.create(
                    organisation=emr.organisation,
                    patient=patient,
                    scheduled_for=timezone.now(),
                    status="triage",
                    encounter_type=enc_type,
                    queue_number=next_q,
                    notes=chief,
                    created_by=request.user,
                )
            else:
                appt.status = "triage"
                appt.encounter_type = enc_type
                if chief:
                    appt.notes = chief
                appt.save(update_fields=["status", "encounter_type", "notes", "updated_at"])

            encounter = existing_encounter or appt.encounters.order_by("-created_at").first()
            if encounter is None:
                encounter = Encounter.objects.create(
                    organisation=emr.organisation,
                    patient=patient,
                    appointment=appt,
                    encounter_date=today,
                    encounter_type=enc_type,
                    chief_complaint=chief,
                    created_by=request.user,
                    updated_by=request.user,
                )
            elif chief:
                encounter.chief_complaint = chief
                encounter.save(update_fields=["chief_complaint", "updated_at"])

            if _form_has_meaningful_data(vitals_form.cleaned_data):
                vital = vitals_form.save(commit=False)
                vital.organisation = emr.organisation
                vital.patient = patient
                vital.encounter = encounter
                vital.recorded_by = request.user
                vital.save()

        log_audit_event(
            request,
            emr.organisation,
            action="update",
            resource_type="intake",
            resource_id=patient.pk,
            detail=f"Intake {'updated' if active_appt else 'queued'} {patient.display_name}",
        )
        messages.success(
            request,
            f"{patient.display_name}'s intake updated." if active_appt
            else f"{patient.display_name} sent to the doctor's queue.",
        )
        return redirect("emr:dashboard")

    _existing_chief = ""
    if existing_encounter and existing_encounter.chief_complaint:
        _existing_chief = existing_encounter.chief_complaint
    elif active_appt and active_appt.notes:
        _existing_chief = active_appt.notes
    return render(
        request,
        "emr/intake_form.html",
        {
            **_base_context(request),
            "patient": patient,
            "vitals_form": vitals_form,
            "last_vitals": patient.vitals.order_by("-recorded_at").first(),
            "already_in_queue": bool(active_appt),
            "intake_chief": _existing_chief,
            "intake_type": active_appt.encounter_type if active_appt else "acute",
            "encounter_type_choices": Encounter._meta.get_field("encounter_type").choices,
        },
    )


@login_required
@require_POST
def patient_add_to_queue_view(request, patient_pk):
    """Put a patient into the doctor's waiting queue (today's appointment → triage)."""
    emr = _require(
        lambda membership: membership.can_manage_schedule(),
        request,
        "Your role cannot manage the queue.",
    )
    if emr is None:
        return redirect("emr:dashboard")
    patient = get_object_or_404(Patient, pk=patient_pk, organisation=emr.organisation)
    today = timezone.localdate()
    with transaction.atomic():
        appt = (
            Appointment.objects.filter(
                organisation=emr.organisation,
                patient=patient,
                scheduled_for__date=today,
                status__in=["scheduled", "checked_in", "triage", "with_doctor"],
            )
            .order_by("scheduled_for")
            .first()
        )
        if appt is None:
            next_q = (
                Appointment.objects.filter(
                    organisation=emr.organisation, scheduled_for__date=today
                ).aggregate(m=Max("queue_number"))["m"] or 0
            ) + 1
            Appointment.objects.create(
                organisation=emr.organisation,
                patient=patient,
                scheduled_for=timezone.now(),
                status="triage",
                queue_number=next_q,
                created_by=request.user,
            )
        else:
            appt.status = "triage"
            appt.save(update_fields=["status", "updated_at"])
    messages.success(request, f"{patient.display_name} added to the queue.")
    return redirect(request.POST.get("next") or "emr:dashboard")


@login_required
@require_POST
def scribe_link_patient_view(request, session_pk):
    """Link a scribe session to an existing patient (opt-in 'Add to EMR').

    Sets ScribeSession.patient so the note joins that patient's history and
    becomes findable in the EMR - without forcing every scribe note into the
    EMR (scribe-only stays the default).
    """
    emr = membership_for_request(request)
    session = get_object_or_404(_scribe_queryset_for_user(request.user), pk=session_pk)
    patient = get_object_or_404(
        Patient, pk=request.POST.get("patient_id"), organisation=emr.organisation
    )
    session.patient = patient
    session.save(update_fields=["patient"])
    log_audit_event(
        request,
        emr.organisation,
        action="update",
        resource_type="scribe_session",
        resource_id=session.pk,
        detail=f"Linked scribe note to {patient.display_name}",
    )
    messages.success(request, f"Note added to {patient.display_name}'s record.")
    return redirect("emr:patient_detail", pk=patient.pk)


@login_required
@require_POST
def encounter_addendum_view(request, encounter_pk):
    """Append an addendum to an encounter (allowed even when signed - the
    original record is never altered)."""
    emr = _require(
        lambda membership: membership.can_edit_encounters(),
        request,
        "Your role cannot add to encounters.",
    )
    if emr is None:
        return redirect("emr:dashboard")
    from .models import EncounterAddendum
    encounter = get_object_or_404(Encounter, pk=encounter_pk, organisation=emr.organisation)
    text = (request.POST.get("text") or "").strip()
    if text:
        EncounterAddendum.objects.create(
            organisation=emr.organisation, encounter=encounter,
            author=request.user, text=text,
        )
        log_audit_event(
            request, emr.organisation, action="create", resource_type="addendum",
            resource_id=encounter.pk, detail=f"Added addendum to encounter {encounter.pk}",
        )
        messages.success(request, "Addendum added.")
    return redirect("emr:encounter_edit", patient_pk=encounter.patient_id, encounter_pk=encounter.pk)


@login_required
def scribe_intake_view(request, session_pk):
    emr = membership_for_request(request)
    session = get_object_or_404(_scribe_queryset_for_user(request.user), pk=session_pk)
    query = request.GET.get("q", "").strip()
    if not query:
        query = session.patient_name or session.patient_identifier or ""
    results = search_patients(emr.organisation, query) if query else []

    return render(
        request,
        "emr/scribe_intake.html",
        {
            **_base_context(request),
            "session": session,
            "query": query,
            "results": results,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def referral_create_view(request, encounter_pk):
    emr = _require(
        lambda membership: membership.can_edit_encounters(),
        request,
        "Your role cannot create referrals.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    encounter = get_object_or_404(
        Encounter.objects.select_related("patient"),
        pk=encounter_pk,
        organisation=emr.organisation,
    )
    initial = {
        "reason": encounter.chief_complaint,
        "clinical_summary": encounter.assessment_notes or encounter.plan_notes,
        "referral_date": timezone.localdate(),
    }
    form = ReferralForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        referral = form.save(commit=False)
        referral.organisation = emr.organisation
        referral.patient = encounter.patient
        referral.encounter = encounter
        referral.referring_provider = request.user
        referral.current_medications_snapshot = [
            {
                "generic": med.drug_name_generic,
                "brand": med.drug_name_brand,
                "dose": str(med.dose_amount or ""),
                "unit": med.dose_unit,
                "frequency": med.frequency,
            }
            for med in encounter.medications.filter(status="active")
        ]
        referral.save()
        log_audit_event(
            request,
            emr.organisation,
            action="create",
            resource_type="referral",
            resource_id=referral.pk,
            detail=f"Created referral for {encounter.patient.display_name}",
        )
        messages.success(request, "Referral drafted.")
        return redirect("emr:referral_print", referral_pk=referral.pk)

    return render(
        request,
        "emr/referral_form.html",
        {
            **_base_context(request),
            "form": form,
            "encounter": encounter,
            "patient": encounter.patient,
        },
    )


@login_required
def prescription_print_view(request, encounter_pk):
    emr = membership_for_request(request)
    encounter = get_object_or_404(
        Encounter.objects.select_related("patient", "provider"),
        pk=encounter_pk,
        organisation=emr.organisation,
    )
    medications = encounter.medications.exclude(status="discontinued").order_by("drug_name_generic")
    log_audit_event(
        request,
        emr.organisation,
        action="export",
        resource_type="prescription",
        resource_id=encounter.pk,
        detail=f"Opened prescription print view for {encounter.patient.display_name}",
    )
    return render(
        request,
        "emr/prescription_print.html",
        {
            **_base_context(request),
            "encounter": encounter,
            "patient": encounter.patient,
            "medications": medications,
        },
    )


@login_required
def referral_print_view(request, referral_pk):
    emr = membership_for_request(request)
    referral = get_object_or_404(
        Referral.objects.select_related("patient", "encounter", "referring_provider"),
        pk=referral_pk,
        organisation=emr.organisation,
    )
    log_audit_event(
        request,
        emr.organisation,
        action="export",
        resource_type="referral",
        resource_id=referral.pk,
        detail=f"Opened referral print view for {referral.patient.display_name}",
    )
    return render(
        request,
        "emr/referral_print.html",
        {
            **_base_context(request),
            "referral": referral,
            "patient": referral.patient,
            "encounter": referral.encounter,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def organisation_settings_view(request):
    emr = _require(
        lambda membership: membership.is_admin,
        request,
        "Only organisation admins can edit clinic settings.",
    )
    if emr is None:
        return redirect("emr:dashboard")

    form = OrganisationForm(request.POST or None, instance=emr.organisation)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_audit_event(
            request,
            emr.organisation,
            action="update",
            resource_type="organisation",
            resource_id=emr.organisation.pk,
            detail="Updated organisation settings",
        )
        messages.success(request, "Organisation settings updated.")
        return redirect("emr:settings")

    memberships = (
        OrganisationMembership.objects.filter(organisation=emr.organisation)
        .select_related("user")
        .order_by("role", "user__username")
    )
    audit_events = emr.organisation.audit_events.select_related("user")[:20]

    return render(
        request,
        "emr/organisation_settings.html",
        {
            **_base_context(request),
            "form": form,
            "memberships": memberships,
            "audit_events": audit_events,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# GNU Health / external EMR bridge API
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@require_http_methods(["GET"])
def gnuhealth_status_api(request):
    """GET /emr/api/gnuhealth/status/ - check connection to configured EMR backend."""
    from .backends import get_backend

    try:
        backend = get_backend()
        result = backend.health_check()
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    return JsonResponse(result)


@login_required
@require_http_methods(["GET"])
def gnuhealth_patient_search_api(request):
    """GET /emr/api/gnuhealth/patients/?q=... - search patients in configured backend."""
    from .backends import get_backend

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"patients": [], "query": q})

    try:
        backend = get_backend()
        patients = backend.search_patients(q, limit=20)
        return JsonResponse({"patients": patients, "query": q})
    except Exception as exc:
        logger.error("gnuhealth_patient_search_api error: %s", exc)
        return JsonResponse({"error": str(exc), "patients": []}, status=500)


@login_required
@require_http_methods(["POST"])
def gnuhealth_push_session_api(request, session_pk: int):
    """
    POST /emr/api/gnuhealth/sessions/<pk>/push/

    Push a finalized ScribeSession to the configured EMR backend as a new patient
    encounter.  Optional JSON body:
      {
        "patient_id":  "<backend native id>",   // if known
        "create_patient": true                  // create patient if not found
      }

    Response:
      {"ok": true, "encounter_id": "...", "patient_id": "...", "backend": "..."}
    """
    from .backends import get_backend

    session = get_object_or_404(ScribeSession, pk=session_pk, user=request.user)
    note = getattr(session, "note", None)

    body: dict = {}
    if request.content_type and "json" in request.content_type:
        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

    try:
        backend = get_backend()
    except Exception as exc:
        return JsonResponse({"error": f"Backend error: {exc}"}, status=500)

    # ── Resolve patient ────────────────────────────────────────────────────────
    patient_id = body.get("patient_id")
    if not patient_id:
        # Attempt to find/create from session metadata
        patient_name = session.patient_name or session.chief_complaint or "Unknown"
        if body.get("create_patient"):
            try:
                parts = patient_name.split()
                new_patient = backend.create_patient({
                    "first_name": parts[0] if parts else patient_name,
                    "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
                    "full_name": patient_name,
                    "dob": session.patient_dob or "",
                    "sex": "u",
                })
                patient_id = new_patient["id"]
            except Exception as exc:
                return JsonResponse({"error": f"Could not create patient: {exc}"}, status=500)
        else:
            return JsonResponse(
                {
                    "error": "patient_id required. Pass patient_id or set create_patient=true.",
                    "hint": "Search patients at /emr/api/gnuhealth/patients/?q=<name>",
                },
                status=400,
            )

    # ── Build encounter payload ────────────────────────────────────────────────
    full_note = ""
    if note:
        full_note = note.edited_note or note.full_note or ""

    encounter_data = {
        "chief_complaint": session.chief_complaint or "",
        "clinical_summary": full_note,
        "subjective": note.subjective if note else "",
        "objective": note.objective if note else "",
        "assessment": note.assessment if note else "",
        "plan": note.plan if note else "",
        "encounter_date": str(session.created_at.date()),
    }

    # ── Push ──────────────────────────────────────────────────────────────────
    try:
        encounter = backend.push_encounter(patient_id, encounter_data)
    except Exception as exc:
        logger.error("gnuhealth_push_session_api push_encounter error: %s", exc)
        return JsonResponse({"error": f"Push failed: {exc}"}, status=500)

    log_audit_event(
        user=request.user,
        action="gnuhealth_push",
        resource_type="ScribeSession",
        resource_id=session_pk,
        detail=f"Pushed to {encounter.get('_backend','?')} encounter {encounter.get('id','?')}",
    )
    return JsonResponse(
        {
            "ok": True,
            "encounter_id": encounter.get("id"),
            "patient_id": patient_id,
            "backend": encounter.get("_backend"),
        }
    )
