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
from django.http import JsonResponse
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
    """AJAX endpoint — returns live board state as JSON (30-second polling)."""
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
        qs = EDVisit.objects.filter(organisation=org, arrived_at__date=today).select_related(
            "patient", "triage_nurse", "attending_physician"
        ).prefetch_related("triage")

        if status_filter:
            qs = qs.filter(current_status=status_filter)

        ctx["visits"] = qs.order_by("-arrived_at")
        ctx["today"] = today
        ctx["status_filter"] = status_filter
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
        return render(request, self.template_name, {
            "form": form,
            "visit": visit,
            "is_retriage": is_retriage,
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
                f"{action} complete — ESI {esi}, zone: {visit.get_current_zone_display()}."
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
    """Quick zone reassignment — POST only."""
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
    """AJAX zone assignment — JSON POST."""
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
        return render(request, self.template_name, {"form": form, "visit": visit})

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

        messages.error(request, "Could not open shift — check the form.")
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
