"""Emergency Department views.

Covers the full patient journey:
  Arrival → Triage → Zone → Physician assessment → Disposition → Exit

Plus shift management and AI-assisted handover.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from emr.models import Organisation, OrganisationMembership, Patient

from .forms import (
    DispositionForm,
    HandoverNoteForm,
    NewVisitForm,
    ShiftOpenForm,
    TriageAssessmentForm,
    ZoneAssignForm,
)
from .models import (
    ZONE_CHOICES,
    DispositionRecord,
    EDShift,
    EDVisit,
    ShiftHandoverNote,
    TriageAssessment,
    ZoneAssignment,
)
from .services.ai_esi import suggest_esi
from .services.handover import generate_sbar, generate_all_sbar

logger = logging.getLogger(__name__)

_VITALS_EXTRACT_PROMPT = """\
You are a clinical data extraction assistant for an ED triage system.
Extract structured vital sign data and chief complaint from the nurse's transcript.

Return ONLY valid JSON - no text outside the JSON object:
{
  "chief_complaint": "<concise chief complaint or empty string>",
  "bp_systolic": <integer or null>,
  "bp_diastolic": <integer or null>,
  "pulse_bpm": <integer or null>,
  "rr_rpm": <integer or null>,
  "temp_celsius": <number or null>,
  "spo2_percent": <number or null>,
  "pain_score": <integer 0-10 or null>,
  "weight_kg": <number or null>,
  "blood_glucose_mmol": <number or null>
}

Rules:
- Only include fields explicitly mentioned in the transcript
- For blood pressure spoken as "130 over 85" → systolic=130, diastolic=85
- For temperature convert Fahrenheit to Celsius if "F" mentioned
- For pain: "pain 7 out of 10" → 7
- If a value is not mentioned, set it to null
- chief_complaint: if the patient describes symptoms, summarize as a clinical complaint
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_org(request):
    """Return the user's default organisation or first membership."""
    try:
        m = request.user.organisation_memberships.select_related("organisation").filter(
            is_default=True
        ).first()
        if not m:
            m = request.user.organisation_memberships.select_related("organisation").first()
        return m.organisation if m else None
    except Exception:
        return None


def _active_visits(org):
    """All non-discharged visits for this org, ordered by zone then arrival."""
    return (
        EDVisit.objects.filter(organisation=org)
        .exclude(current_status__in=["discharged", "admitted", "transferred", "absconded", "deceased"])
        .select_related("patient", "triage_nurse", "attending_physician")
        .prefetch_related("triage")
        .order_by("current_zone", "arrived_at")
    )


def _zone_board(org):
    """Group active visits by zone for the tracking board."""
    visits = _active_visits(org)
    zones = {key: [] for key, _ in ZONE_CHOICES}
    for v in visits:
        zones[v.current_zone].append(v)
    return zones


# ---------------------------------------------------------------------------
# Tracking Board
# ---------------------------------------------------------------------------

class TrackingBoardView(LoginRequiredMixin, TemplateView):
    template_name = "ed/tracking_board.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = _get_user_org(self.request)
        ctx["org"] = org
        ctx["zone_board"] = _zone_board(org) if org else {}
        ctx["zone_labels"] = dict(ZONE_CHOICES)
        ctx["total_active"] = sum(len(v) for v in ctx["zone_board"].values())
        ctx["critical_count"] = sum(
            1 for v in _active_visits(org)
            if v.esi_score in (1, 2)
        ) if org else 0
        # Current open shift
        ctx["current_shift"] = (
            EDShift.objects.filter(organisation=org, closed_at__isnull=True)
            .order_by("-opened_at")
            .first()
        ) if org else None
        return ctx


@login_required
def board_json(request):
    """AJAX endpoint - returns live board state as JSON (30-second polling)."""
    org = _get_user_org(request)
    if not org:
        return JsonResponse({"error": "No organisation"}, status=400)

    visits_data = []
    for v in _active_visits(org):
        entry = {
            "pk": v.pk,
            "visit_number": v.visit_number,
            "display_name": v.display_name,
            "esi": v.esi_score,
            "esi_color": v.esi_color_class,
            "chief_complaint": v.chief_complaint,
            "status": v.current_status,
            "status_display": v.get_current_status_display(),
            "zone": v.current_zone,
            "zone_display": v.get_current_zone_display(),
            "bed": v.current_bed,
            "zone_color": v.zone_color_class,
            "time_in_dept": v.time_in_department_minutes,
            "doctor": (
                v.attending_physician.get_full_name()
                or v.attending_physician.username
            ) if v.attending_physician else "",
            "detail_url": f"/ed/visits/{v.pk}/",
        }
        try:
            t = v.triage
            entry["has_critical_vitals"] = t.has_critical_vitals
            entry["vital_flags"] = t.vital_flags
        except TriageAssessment.DoesNotExist:
            entry["has_critical_vitals"] = False
            entry["vital_flags"] = []
        visits_data.append(entry)

    return JsonResponse({"visits": visits_data, "timestamp": timezone.now().isoformat()})


# ---------------------------------------------------------------------------
# Visit list (today)
# ---------------------------------------------------------------------------

class VisitListView(LoginRequiredMixin, TemplateView):
    template_name = "ed/visit_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = _get_user_org(self.request)
        today = date.today()

        status_filter = self.request.GET.get("status", "")
        search_q = self.request.GET.get("q", "").strip()
        qs = EDVisit.objects.filter(organisation=org, arrived_at__date=today).select_related(
            "patient", "triage_nurse", "attending_physician"
        ).prefetch_related("triage")

        if status_filter:
            qs = qs.filter(current_status=status_filter)
        if search_q:
            from django.db.models import Q
            qs = qs.filter(
                Q(patient_name_unregistered__icontains=search_q)
                | Q(patient__legal_first_name__icontains=search_q)
                | Q(patient__legal_last_name__icontains=search_q)
                | Q(visit_number__icontains=search_q)
                | Q(triage__chief_complaint__icontains=search_q)
            )

        ctx["visits"] = qs.order_by("-arrived_at")
        ctx["today"] = today
        ctx["status_filter"] = status_filter
        ctx["search_q"] = search_q
        ctx["total_today"] = EDVisit.objects.filter(
            organisation=org, arrived_at__date=today
        ).count()
        return ctx


# ---------------------------------------------------------------------------
# New Visit (arrival registration)
# ---------------------------------------------------------------------------

class NewVisitView(LoginRequiredMixin, View):
    template_name = "ed/new_visit.html"

    def get(self, request):
        org = _get_user_org(request)
        form = NewVisitForm()
        patient_search = request.GET.get("q", "")
        patients = []
        if patient_search and org:
            patients = Patient.objects.filter(
                organisation=org
            ).filter(
                legal_last_name__icontains=patient_search
            ) | Patient.objects.filter(
                organisation=org
            ).filter(
                legal_first_name__icontains=patient_search
            )
            patients = patients[:10]
        return render(request, self.template_name, {
            "form": form,
            "patients": patients,
            "patient_search": patient_search,
            "org": org,
        })

    def post(self, request):
        org = _get_user_org(request)
        if not org:
            messages.error(request, "You are not associated with an organisation.")
            return redirect("ed:board")

        form = NewVisitForm(request.POST)
        if form.is_valid():
            visit = form.save(commit=False)
            visit.organisation = org
            visit.created_by = request.user

            patient_id = request.POST.get("patient_id")
            if patient_id:
                try:
                    visit.patient = Patient.objects.get(pk=patient_id, organisation=org)
                except Patient.DoesNotExist:
                    pass

            if not visit.patient and not visit.patient_name_unregistered:
                visit.patient_name_unregistered = "Unknown"

            visit.save()
            messages.success(request, f"Visit {visit.visit_number} created. Proceed to triage.")
            return redirect("ed:triage_form", pk=visit.pk)

        return render(request, self.template_name, {"form": form, "org": org})


# ---------------------------------------------------------------------------
# Visit Detail (full timeline)
# ---------------------------------------------------------------------------

class VisitDetailView(LoginRequiredMixin, DetailView):
    model = EDVisit
    template_name = "ed/visit_detail.html"
    context_object_name = "visit"

    def get_queryset(self):
        org = _get_user_org(self.request)
        return EDVisit.objects.filter(organisation=org).select_related(
            "patient", "triage_nurse", "charge_nurse", "attending_physician",
            "emr_encounter",
        ).prefetch_related("triage", "zone_history", "handover_notes")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        visit = self.object
        ctx["zone_form"] = ZoneAssignForm(initial={
            "zone": visit.current_zone,
            "bed_number": visit.current_bed,
        })
        try:
            ctx["triage"] = visit.triage
        except TriageAssessment.DoesNotExist:
            ctx["triage"] = None
        try:
            ctx["disposition"] = visit.disposition
        except DispositionRecord.DoesNotExist:
            ctx["disposition"] = None
        ctx["zone_history"] = visit.zone_history.select_related("assigned_by").order_by("-assigned_at")
        return ctx


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

class TriageFormView(LoginRequiredMixin, View):
    template_name = "ed/triage_form.html"

    def _get_visit(self, request, pk):
        org = _get_user_org(request)
        return get_object_or_404(EDVisit, pk=pk, organisation=org)

    def get(self, request, pk):
        visit = self._get_visit(request, pk)
        try:
            existing = visit.triage
            form = TriageAssessmentForm(instance=existing)
            is_retriage = True
        except TriageAssessment.DoesNotExist:
            form = TriageAssessmentForm()
            is_retriage = False

        # --- Past life reminder (DKA story) ---
        # Surface the patient's known history BEFORE the nurse has to ask.
        prior_pmh: list[str] = []
        prior_visits: list[dict] = []
        if visit.patient:
            past_triages = (
                TriageAssessment.objects
                .filter(visit__patient=visit.patient, visit__organisation=visit.organisation)
                .exclude(visit=visit)
                .select_related("visit")
                .order_by("-assessed_at")[:5]
            )
            pmh_seen: set[str] = set()
            for t in past_triages:
                for flag in t.pmh_list:
                    if flag not in pmh_seen:
                        prior_pmh.append(flag)
                        pmh_seen.add(flag)
                if t.chief_complaint:
                    prior_visits.append({
                        "date": t.assessed_at,
                        "cc": t.chief_complaint,
                        "esi": t.esi_score,
                    })

        return render(request, self.template_name, {
            "form": form,
            "visit": visit,
            "is_retriage": is_retriage,
            "prior_pmh": prior_pmh,
            "prior_visits": prior_visits[:3],
        })

    def post(self, request, pk):
        visit = self._get_visit(request, pk)
        try:
            existing = visit.triage
            form = TriageAssessmentForm(request.POST, instance=existing)
            is_retriage = True
        except TriageAssessment.DoesNotExist:
            form = TriageAssessmentForm(request.POST)
            is_retriage = False

        if form.is_valid():
            assessment = form.save(commit=False)
            assessment.visit = visit
            assessment.assessed_by = request.user
            if is_retriage:
                assessment.re_triage = True
            assessment.save()

            # Update visit timestamps + status
            now = timezone.now()
            if not visit.triaged_at:
                visit.triaged_at = now
            visit.triage_nurse = request.user
            visit.current_status = "triaged"

            # Auto-suggest zone based on ESI
            esi = assessment.esi_score
            auto_zone = {
                1: "resus",
                2: "acute",
                3: "acute",
                4: "fast_track",
                5: "fast_track",
            }.get(esi, "waiting")

            if visit.current_zone == "waiting":
                visit.current_zone = auto_zone
                visit.zone_assigned_at = now
                ZoneAssignment.objects.create(
                    visit=visit,
                    zone=auto_zone,
                    assigned_by=request.user,
                    notes=f"Auto-assigned based on ESI {esi}",
                )

            visit.save()
            action = "Re-triage" if is_retriage else "Triage"
            messages.success(
                request,
                f"{action} complete - ESI {esi}, zone: {visit.get_current_zone_display()}."
            )
            return redirect("ed:visit_detail", pk=visit.pk)

        return render(request, self.template_name, {
            "form": form,
            "visit": visit,
            "is_retriage": is_retriage,
        })


# ---------------------------------------------------------------------------
# Physician View
# ---------------------------------------------------------------------------

class PhysicianView(LoginRequiredMixin, View):
    template_name = "ed/physician_view.html"

    def _get_visit(self, request, pk):
        org = _get_user_org(request)
        return get_object_or_404(EDVisit, pk=pk, organisation=org)

    def get(self, request, pk):
        visit = self._get_visit(request, pk)

        # Mark door-to-doctor timestamp on first open
        if not visit.seen_by_doctor_at:
            visit.seen_by_doctor_at = timezone.now()
            if not visit.attending_physician:
                visit.attending_physician = request.user
            visit.current_status = "with_doctor"
            visit.save(update_fields=["seen_by_doctor_at", "attending_physician", "current_status"])

        try:
            triage = visit.triage
        except TriageAssessment.DoesNotExist:
            triage = None

        return render(request, self.template_name, {
            "visit": visit,
            "triage": triage,
        })


# ---------------------------------------------------------------------------
# Zone Assignment
# ---------------------------------------------------------------------------

@login_required
def zone_assign_view(request, pk):
    """Quick zone reassignment - POST only."""
    org = _get_user_org(request)
    visit = get_object_or_404(EDVisit, pk=pk, organisation=org)

    if request.method == "POST":
        form = ZoneAssignForm(request.POST)
        if form.is_valid():
            new_zone = form.cleaned_data["zone"]
            bed = form.cleaned_data.get("bed_number", "")
            notes = form.cleaned_data.get("notes", "")

            # Close previous open assignment
            now = timezone.now()
            ZoneAssignment.objects.filter(visit=visit, ended_at__isnull=True).update(ended_at=now)

            ZoneAssignment.objects.create(
                visit=visit,
                zone=new_zone,
                bed_number=bed,
                assigned_by=request.user,
                notes=notes,
            )
            visit.current_zone = new_zone
            visit.current_bed = bed
            visit.zone_assigned_at = now
            if visit.current_status == "triaged":
                visit.current_status = "in_zone"
            visit.save(update_fields=["current_zone", "current_bed", "zone_assigned_at", "current_status"])
            messages.success(request, f"Moved to {visit.get_current_zone_display()} {bed}.")

    return redirect("ed:visit_detail", pk=pk)


@login_required
def zone_assign_api(request, pk):
    """AJAX zone assignment - JSON POST."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    org = _get_user_org(request)
    visit = get_object_or_404(EDVisit, pk=pk, organisation=org)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    new_zone = data.get("zone")
    bed = data.get("bed_number", "")
    notes = data.get("notes", "")

    valid_zones = {k for k, _ in ZONE_CHOICES}
    if new_zone not in valid_zones:
        return JsonResponse({"error": "Invalid zone"}, status=400)

    now = timezone.now()
    ZoneAssignment.objects.filter(visit=visit, ended_at__isnull=True).update(ended_at=now)
    ZoneAssignment.objects.create(
        visit=visit,
        zone=new_zone,
        bed_number=bed,
        assigned_by=request.user,
        notes=notes,
    )
    visit.current_zone = new_zone
    visit.current_bed = bed
    visit.zone_assigned_at = now
    if visit.current_status == "triaged":
        visit.current_status = "in_zone"
    visit.save(update_fields=["current_zone", "current_bed", "zone_assigned_at", "current_status"])

    return JsonResponse({
        "ok": True,
        "zone": new_zone,
        "zone_display": visit.get_current_zone_display(),
        "bed": bed,
    })


# ---------------------------------------------------------------------------
# Disposition
# ---------------------------------------------------------------------------

class DispositionView(LoginRequiredMixin, View):
    template_name = "ed/disposition_form.html"

    def _get_visit(self, request, pk):
        org = _get_user_org(request)
        return get_object_or_404(EDVisit, pk=pk, organisation=org)

    def get(self, request, pk):
        visit = self._get_visit(request, pk)
        try:
            existing = visit.disposition
            form = DispositionForm(instance=existing)
        except DispositionRecord.DoesNotExist:
            form = DispositionForm()

        # Discharge safety check - surface any abnormal vitals to the doctor
        vital_flags: list[str] = []
        try:
            vital_flags = visit.triage.vital_flags
        except TriageAssessment.DoesNotExist:
            pass

        return render(request, self.template_name, {
            "form": form,
            "visit": visit,
            "vital_flags": vital_flags,
        })

    def post(self, request, pk):
        visit = self._get_visit(request, pk)
        try:
            existing = visit.disposition
            form = DispositionForm(request.POST, instance=existing)
        except DispositionRecord.DoesNotExist:
            form = DispositionForm(request.POST)

        if form.is_valid():
            disp = form.save(commit=False)
            disp.visit = visit
            disp.decided_by = request.user
            disp.decided_at = timezone.now()
            disp.save()

            # Update visit status + timestamps
            now = timezone.now()
            if not visit.disposition_decided_at:
                visit.disposition_decided_at = now

            status_map = {
                "discharge_home": "discharged",
                "admit_general": "admitted",
                "admit_icu": "admitted",
                "admit_hdu": "admitted",
                "admit_paeds": "admitted",
                "admit_maternity": "admitted",
                "transfer": "transferred",
                "dama": "discharged",
                "absconded": "absconded",
                "deceased": "deceased",
            }
            visit.current_status = status_map.get(disp.disposition, "disposition_pending")
            if visit.current_status in {"discharged", "admitted", "transferred", "absconded", "deceased"}:
                visit.exited_at = now
            visit.save(update_fields=[
                "current_status", "disposition_decided_at", "exited_at"
            ])

            messages.success(
                request,
                f"Disposition recorded: {disp.get_disposition_display()}."
            )
            return redirect("ed:visit_detail", pk=pk)

        return render(request, self.template_name, {"form": form, "visit": visit})


# ---------------------------------------------------------------------------
# AI ESI Suggestion API
# ---------------------------------------------------------------------------

@login_required
def triage_voice_extract_api(request, pk):
    """POST: extract triage fields from a spoken transcript.

    Body: {"transcript": "patient says chest pain, BP 140 over 90, HR 102…"}
    Returns: JSON with field suggestions the JS can auto-fill into the form.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    transcript = (data.get("transcript") or "").strip()
    if not transcript:
        return JsonResponse({"error": "No transcript provided"}, status=400)

    try:
        from scribe.services.clients import get_chat_client
        from django.conf import settings as _settings
        client = get_chat_client()
        deployment = getattr(_settings, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _VITALS_EXTRACT_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
            max_tokens=300,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
        result["transcript"] = transcript
        return JsonResponse({"ok": True, "fields": result})
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "AI returned non-JSON", "transcript": transcript})
    except Exception as exc:
        logger.error("Triage voice extract failed: %s", exc)
        return JsonResponse({"ok": False, "error": str(exc), "transcript": transcript})


@login_required
def esi_ai_api(request, pk):
    """POST: run AI ESI suggestion for a visit based on submitted vitals."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    age = None
    org = _get_user_org(request)
    visit = get_object_or_404(EDVisit, pk=pk, organisation=org)
    if visit.patient and visit.patient.date_of_birth:
        from django.utils.timezone import localdate
        today = localdate()
        dob = visit.patient.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    suggestion = suggest_esi(
        chief_complaint=data.get("chief_complaint", ""),
        mechanism=data.get("mechanism", "medical"),
        temp_celsius=data.get("temp_celsius"),
        bp_systolic=data.get("bp_systolic"),
        bp_diastolic=data.get("bp_diastolic"),
        pulse_bpm=data.get("pulse_bpm"),
        rr_rpm=data.get("rr_rpm"),
        spo2_percent=data.get("spo2_percent"),
        pain_score=data.get("pain_score"),
        gcs_total=data.get("gcs_total"),
        pmh_list=data.get("pmh_list", []),
        age=age,
    )

    return JsonResponse({
        "esi": suggestion.esi,
        "rationale": suggestion.rationale,
        "flags": suggestion.flags,
        "confidence": suggestion.confidence,
        "error": suggestion.error,
    })


# ---------------------------------------------------------------------------
# Shift Management
# ---------------------------------------------------------------------------

class ShiftListView(LoginRequiredMixin, TemplateView):
    template_name = "ed/shift_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = _get_user_org(self.request)
        ctx["shifts"] = EDShift.objects.filter(organisation=org).select_related(
            "charge_nurse", "opened_by", "closed_by"
        )[:30]
        ctx["current_shift"] = (
            EDShift.objects.filter(organisation=org, closed_at__isnull=True)
            .order_by("-opened_at")
            .first()
        )
        ctx["open_form"] = ShiftOpenForm(initial={"shift_date": date.today()})
        return ctx


class ShiftOpenView(LoginRequiredMixin, View):
    template_name = "ed/shift_list.html"

    def post(self, request):
        org = _get_user_org(request)
        if not org:
            messages.error(request, "No organisation found.")
            return redirect("ed:shifts")

        form = ShiftOpenForm(request.POST)
        if form.is_valid():
            shift = form.save(commit=False)
            shift.organisation = org
            shift.opened_by = request.user
            shift.charge_nurse = request.user
            shift.save()
            messages.success(request, f"Shift opened: {shift.get_shift_type_display()} on {shift.shift_date}.")
            return redirect("ed:handover", pk=shift.pk)

        messages.error(request, "Could not open shift - check the form.")
        return redirect("ed:shifts")


@login_required
def shift_close_view(request, pk):
    """Close a shift (POST)."""
    org = _get_user_org(request)
    shift = get_object_or_404(EDShift, pk=pk, organisation=org)
    if request.method == "POST":
        shift.closed_by = request.user
        shift.closed_at = timezone.now()
        shift.census_at_close = _active_visits(org).count()
        shift.save(update_fields=["closed_by", "closed_at", "census_at_close"])
        messages.success(request, "Shift closed.")
    return redirect("ed:shifts")


# ---------------------------------------------------------------------------
# Handover
# ---------------------------------------------------------------------------

class HandoverView(LoginRequiredMixin, View):
    template_name = "ed/shift_handover.html"

    def get(self, request, pk):
        org = _get_user_org(request)
        shift = get_object_or_404(EDShift, pk=pk, organisation=org)
        active = _active_visits(org)

        # Load or stub SBAR notes for each active visit
        existing_notes = {n.visit_id: n for n in shift.handover_notes.all()}
        patient_notes = []
        for v in active:
            note = existing_notes.get(v.pk)
            form = HandoverNoteForm(instance=note, prefix=f"v{v.pk}")
            patient_notes.append({"visit": v, "note": note, "form": form})

        return render(request, self.template_name, {
            "shift": shift,
            "patient_notes": patient_notes,
            "active_count": active.count(),
        })

    def post(self, request, pk):
        org = _get_user_org(request)
        shift = get_object_or_404(EDShift, pk=pk, organisation=org)
        active = _active_visits(org)
        existing_notes = {n.visit_id: n for n in shift.handover_notes.all()}

        saved = 0
        for v in active:
            note = existing_notes.get(v.pk)
            form = HandoverNoteForm(request.POST, instance=note, prefix=f"v{v.pk}")
            if form.is_valid():
                obj = form.save(commit=False)
                obj.outgoing_shift = shift
                obj.visit = v
                obj.created_by = request.user
                obj.save()
                saved += 1

        messages.success(request, f"Saved {saved} handover notes.")
        return redirect("ed:handover", pk=pk)


@login_required
def handover_generate_api(request, pk):
    """POST: AI-generate SBAR notes for all active patients in this shift."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    org = _get_user_org(request)
    shift = get_object_or_404(EDShift, pk=pk, organisation=org)
    active = _active_visits(org)

    results = generate_all_sbar(shift, active, request.user)

    saved = 0
    for visit_pk, sbar in results.items():
        if sbar.error:
            continue
        visit = next((v for v in active if v.pk == visit_pk), None)
        if not visit:
            continue
        ShiftHandoverNote.objects.update_or_create(
            outgoing_shift=shift,
            visit=visit,
            defaults={
                "situation": sbar.situation,
                "background": sbar.background,
                "assessment": sbar.assessment,
                "recommendation": sbar.recommendation,
                "ai_generated": True,
                "created_by": request.user,
            },
        )
        saved += 1

    return JsonResponse({
        "ok": True,
        "generated": saved,
        "total": active.count(),
    })


# ---------------------------------------------------------------------------
# Triage Voice - combined audio-to-fields (single round-trip)
# ---------------------------------------------------------------------------

@login_required
def triage_voice_audio_api(request, pk):
    """POST multipart/form-data with 'audio' file.

    Server-side: transcribe (cloud Whisper) → extract structured triage fields
    (GPT-4o-mini) in one round-trip, eliminating the extra browser↔server hop.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"ok": False, "error": "No audio file received."}, status=400)

    import os
    import tempfile

    suffix = os.path.splitext(audio.name or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in audio.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    transcript = ""
    try:
        from scribe.services.pipeline import run_transcription
        transcript = (run_transcription(tmp_path) or "").strip()
    except Exception as exc:
        logger.error("ED triage voice transcription failed: %s", exc)
        return JsonResponse({"ok": False, "error": f"Transcription failed: {exc}"}, status=500)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not transcript:
        return JsonResponse({"ok": False, "error": "No speech detected - please try again."})

    fields: dict = {}
    try:
        from scribe.services.clients import get_chat_client
        from django.conf import settings as _settings
        client = get_chat_client()
        deployment = getattr(_settings, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _VITALS_EXTRACT_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
            max_tokens=300,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        fields = json.loads(raw)
    except json.JSONDecodeError:
        pass
    except Exception as exc:
        logger.error("ED triage voice extraction failed: %s", exc)

    return JsonResponse({"ok": True, "transcript": transcript, "fields": fields})


# ---------------------------------------------------------------------------
# ED Settings - AI voice config status
# ---------------------------------------------------------------------------

@login_required
def ed_settings_view(request):
    """Read-only diagnostics page showing which AI providers are wired up."""
    from urllib.parse import urlparse
    from django.conf import settings as _s

    def _host(url: str) -> str:
        try:
            return urlparse(url).hostname or url
        except Exception:
            return url

    # Transcription
    if _s.SCRIBE_AZURE_OPENAI_TRANSCRIBE_KEY and _s.SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT:
        transcription = {
            "provider": "Azure OpenAI",
            "model": _s.SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT or "gpt-4o-transcribe",
            "endpoint": _host(_s.SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT),
            "ok": True,
        }
    elif _s.SCRIBE_OPENAI_API_KEY:
        transcription = {
            "provider": "OpenAI",
            "model": getattr(_s, "SCRIBE_OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe"),
            "endpoint": "api.openai.com",
            "ok": True,
        }
    else:
        transcription = {"provider": "Not configured", "model": "-", "endpoint": "-", "ok": False}

    # Extraction (chat)
    if getattr(_s, "SCRIBE_AZURE_OPENAI_KEY", "") and getattr(_s, "SCRIBE_AZURE_OPENAI_ENDPOINT", ""):
        extraction = {
            "provider": "Azure OpenAI",
            "model": getattr(_s, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            "endpoint": _host(_s.SCRIBE_AZURE_OPENAI_ENDPOINT),
            "ok": True,
        }
    else:
        extraction = {"provider": "Not configured", "model": "-", "endpoint": "-", "ok": False}

    return render(request, "ed/settings.html", {
        "transcription": transcription,
        "extraction": extraction,
    })


# ---------------------------------------------------------------------------
# Visit Export - FHIR R4 JSON + smart clinical summary
# ---------------------------------------------------------------------------

def _build_fhir_bundle(visit: EDVisit) -> dict:
    """Minimal FHIR R4 collection bundle for a single ED visit."""
    import uuid as _uuid

    bundle_id = str(_uuid.uuid4())
    now_iso = timezone.now().isoformat()
    entries = []

    # Patient
    patient_id = f"patient-{visit.pk}"
    if visit.patient:
        p = visit.patient
        name_entry = [{"family": p.legal_last_name, "given": [p.legal_first_name]}]
        gender = (getattr(p, "sex", None) or "unknown").lower()
        dob = p.date_of_birth.isoformat() if getattr(p, "date_of_birth", None) else None
    else:
        parts = (visit.patient_name_unregistered or "Unknown").split(" ", 1)
        given = parts[0]
        family = parts[1] if len(parts) > 1 else parts[0]
        name_entry = [{"family": family, "given": [given]}]
        gender = "unknown"
        dob = None

    patient_res = {"resourceType": "Patient", "id": patient_id, "name": name_entry, "gender": gender}
    if dob:
        patient_res["birthDate"] = dob
    entries.append({"fullUrl": f"urn:uuid:{patient_id}", "resource": patient_res})

    # Encounter
    encounter_id = f"encounter-{visit.pk}"
    encounter_res = {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "in-progress" if visit.is_active else "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "Emergency"},
        "subject": {"reference": f"urn:uuid:{patient_id}"},
        "period": {"start": visit.arrived_at.isoformat()},
        "identifier": [{"value": visit.visit_number}],
    }
    if visit.exited_at:
        encounter_res["period"]["end"] = visit.exited_at.isoformat()
    entries.append({"fullUrl": f"urn:uuid:{encounter_id}", "resource": encounter_res})

    # Vitals + chief complaint from triage
    try:
        t = visit.triage
        vital_map = [
            ("bp_systolic",        "8480-6",  "Systolic blood pressure",  "mmHg"),
            ("bp_diastolic",       "8462-4",  "Diastolic blood pressure", "mmHg"),
            ("pulse_bpm",          "8867-4",  "Heart rate",               "/min"),
            ("rr_rpm",             "9279-1",  "Respiratory rate",         "/min"),
            ("temp_celsius",       "8310-5",  "Body temperature",         "Cel"),
            ("spo2_percent",       "2708-6",  "Oxygen saturation",        "%"),
            ("pain_score",         "72514-3", "Pain severity",            "score"),
            ("weight_kg",          "29463-7", "Body weight",              "kg"),
            ("blood_glucose_mmol", "15074-8", "Glucose",                  "mmol/L"),
        ]
        effective = t.assessed_at.isoformat() if t.assessed_at else now_iso
        for field, loinc, display, unit in vital_map:
            val = getattr(t, field, None)
            if val is None:
                continue
            obs_id = f"obs-{visit.pk}-{field}"
            obs_res = {
                "resourceType": "Observation",
                "id": obs_id,
                "status": "final",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
                "subject": {"reference": f"urn:uuid:{patient_id}"},
                "encounter": {"reference": f"urn:uuid:{encounter_id}"},
                "effectiveDateTime": effective,
                "valueQuantity": {"value": float(val), "unit": unit, "system": "http://unitsofmeasure.org"},
            }
            entries.append({"fullUrl": f"urn:uuid:{obs_id}", "resource": obs_res})

        if t.chief_complaint:
            cond_id = f"cond-{visit.pk}"
            entries.append({"fullUrl": f"urn:uuid:{cond_id}", "resource": {
                "resourceType": "Condition",
                "id": cond_id,
                "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                "subject": {"reference": f"urn:uuid:{patient_id}"},
                "encounter": {"reference": f"urn:uuid:{encounter_id}"},
                "code": {"text": t.chief_complaint},
            }})
    except TriageAssessment.DoesNotExist:
        pass

    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "collection",
        "timestamp": now_iso,
        "entry": entries,
    }


def _build_clinical_summary(visit: EDVisit, triage) -> str:
    """Plain-text clinical summary for clipboard / paste-into-EHR."""
    lines = [
        "── WellnestScribe Clinical Export ──",
        f"Visit:    {visit.visit_number}",
        f"Date:     {visit.arrived_at.strftime('%d %b %Y  %H:%M')}",
        f"Patient:  {visit.display_name}",
        f"Status:   {visit.get_current_status_display()}",
        f"Zone:     {visit.get_current_zone_display()}",
        "",
    ]
    if triage:
        lines += [
            f"CHIEF COMPLAINT: {triage.chief_complaint or '-'}",
            f"ESI Score: {triage.esi_score or '-'}",
            "",
            "VITALS:",
        ]
        v_pairs = [
            ("  BP",       f"{triage.bp_systolic}/{triage.bp_diastolic} mmHg" if triage.bp_systolic else "-"),
            ("  HR",       f"{triage.pulse_bpm} bpm" if triage.pulse_bpm else "-"),
            ("  RR",       f"{triage.rr_rpm} rpm" if triage.rr_rpm else "-"),
            ("  SpO2",     f"{triage.spo2_percent}%" if triage.spo2_percent else "-"),
            ("  Temp",     f"{triage.temp_celsius} °C" if triage.temp_celsius else "-"),
            ("  Weight",   f"{triage.weight_kg} kg" if triage.weight_kg else "-"),
            ("  Pain",     f"{triage.pain_score}/10" if triage.pain_score is not None else "-"),
            ("  BGL",      f"{triage.blood_glucose_mmol} mmol/L" if triage.blood_glucose_mmol else "-"),
        ]
        if triage.gcs_total:
            v_pairs.append(("  GCS", str(triage.gcs_total)))
        for label, val in v_pairs:
            lines.append(f"{label:<10}{val}")
        lines += [
            "",
            f"ALLERGIES:    {triage.allergies or 'NKDA'}",
            f"PMH:          {', '.join(triage.pmh_list) or 'None documented'}",
        ]
        if triage.current_medications:
            lines += ["", "MEDICATIONS:", triage.current_medications]
        if triage.triage_notes:
            lines += ["", "TRIAGE NOTES:", triage.triage_notes]
    if visit.attending_physician:
        lines += ["", f"PHYSICIAN:    {visit.attending_physician.get_full_name() or visit.attending_physician.username}"]
    lines += ["", "── Generated by WellnestScribe ──"]
    return "\n".join(lines)


def _build_hl7_adt(visit: EDVisit, triage) -> str:
    """Minimal HL7 v2.5 ADT^A01 message for legacy HIS integration."""
    from datetime import datetime
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    arrived = visit.arrived_at.strftime("%Y%m%d%H%M")
    name = visit.display_name.replace(" ", "^")
    dob = ""
    sex = "U"
    if visit.patient:
        p = visit.patient
        if getattr(p, "date_of_birth", None):
            dob = p.date_of_birth.strftime("%Y%m%d")
        sex_map = {"male": "M", "female": "F"}
        sex = sex_map.get((getattr(p, "sex", "") or "").lower(), "U")

    segments = [
        f"MSH|^~\\&|WELLNEST|ED|RECEIVING|EHR|{now}||ADT^A01|{visit.visit_number}|P|2.5",
        f"EVN|A01|{now}",
        f"PID|1||{visit.pk}^^^WELLNEST||{name}||{dob}|{sex}",
        f"PV1|1|E|ED^{visit.current_zone}^{visit.current_bed or ''}|{visit.get_current_status_display()}||||||||",
    ]
    if triage:
        segments.append(
            f"OBX|1|NM|8480-6^Systolic BP^LN||{triage.bp_systolic or ''}|mmHg"
        )
        segments.append(
            f"OBX|2|NM|8867-4^Heart rate^LN||{triage.pulse_bpm or ''}|/min"
        )
        segments.append(
            f"OBX|3|NM|2708-6^SpO2^LN||{triage.spo2_percent or ''}|%"
        )
        if triage.chief_complaint:
            segments.append(f"NTE|1||{triage.chief_complaint}")
    return "\r".join(segments)


@login_required
def visit_export_view(request, pk):
    """Export visit data.  ?format=fhir → FHIR R4 JSON download."""
    org = _get_user_org(request)
    visit = get_object_or_404(
        EDVisit.objects.select_related("patient", "triage_nurse", "attending_physician")
                       .prefetch_related("triage"),
        pk=pk, organisation=org,
    )
    fmt = request.GET.get("format", "page")

    if fmt == "fhir":
        bundle = _build_fhir_bundle(visit)
        body = json.dumps(bundle, indent=2)
        resp = HttpResponse(body, content_type="application/fhir+json")
        resp["Content-Disposition"] = f'attachment; filename="visit-{visit.visit_number}-fhir.json"'
        return resp

    try:
        triage = visit.triage
    except TriageAssessment.DoesNotExist:
        triage = None

    clinical_text = _build_clinical_summary(visit, triage)
    hl7_text = _build_hl7_adt(visit, triage)

    return render(request, "ed/visit_export.html", {
        "visit": visit,
        "triage": triage,
        "clinical_text": clinical_text,
        "clinical_text_json": json.dumps(clinical_text),
        "hl7_text_json": json.dumps(hl7_text),
    })
