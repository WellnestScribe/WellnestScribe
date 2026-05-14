"""Views for the modular EMR app."""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from scribe.models import ScribeSession

from .forms import (
    AllergyForm,
    AppointmentForm,
    DiagnosisFormSet,
    EncounterForm,
    MedicationFormSet,
    OrganisationForm,
    PatientForm,
    ReferralForm,
    VitalForm,
    common_code_catalog,
    common_drug_catalog,
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


def _prefill_from_scribe(session: ScribeSession) -> dict:
    note = getattr(session, "note", None)
    if note is None:
        return {
            "chief_complaint": session.chief_complaint,
        }
    return {
        "chief_complaint": session.chief_complaint or note.subjective[:120],
        "history_of_presenting_illness": note.subjective,
        "physical_examination": note.objective,
        "assessment_notes": note.assessment,
        "plan_notes": note.plan or note.edited_note or note.full_note,
        "scribe_session": session,
    }


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
    for obj in diagnosis_formset.deleted_objects:
        obj.delete()
    diagnoses = diagnosis_formset.save(commit=False)
    for diagnosis in diagnoses:
        diagnosis.organisation = organisation
        diagnosis.patient = patient
        diagnosis.encounter = encounter
        diagnosis.diagnosing_provider = request.user
        diagnosis.save()

    for obj in medication_formset.deleted_objects:
        obj.delete()
    medications = medication_formset.save(commit=False)
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

    appointments = (
        Appointment.objects.filter(
            organisation=emr.organisation,
            scheduled_for__range=(day_start, day_end),
        )
        .select_related("patient")
        .order_by("scheduled_for", "queue_number")
    )

    stats = {
        "today": appointments.count(),
        "checked_in": appointments.filter(status="checked_in").count(),
        "triage": appointments.filter(status="triage").count(),
        "with_doctor": appointments.filter(status="with_doctor").count(),
        "complete": appointments.filter(status="complete").count(),
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
def patient_search_view(request):
    emr = membership_for_request(request)
    term = request.GET.get("q", "").strip()
    results = search_patients(emr.organisation, term) if term else []
    recent = []
    if not term:
        recent = Patient.objects.filter(organisation=emr.organisation).order_by("-updated_at")[:12]

    return render(
        request,
        "emr/patient_search.html",
        {
            **_base_context(request),
            "query": term,
            "results": results,
            "recent": recent,
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
        },
    )


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
    appointment.save(update_fields=["status", "updated_at"])
    log_audit_event(
        request,
        emr.organisation,
        action="update",
        resource_type="appointment",
        resource_id=appointment.pk,
        detail=f"Moved {appointment.patient.display_name} to {next_status}",
    )
    messages.success(request, "Worklist updated.")
    return redirect(request.POST.get("next") or reverse("emr:dashboard"))


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
    if is_new and scribe_id:
        scribe_session = get_object_or_404(_scribe_queryset_for_user(request.user), pk=scribe_id)
        initial.update(_prefill_from_scribe(scribe_session))

    provider_queryset = user_choices_for_organisation(emr.organisation)
    scribe_queryset = _scribe_queryset_for_user(request.user)
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
    vitals_form = VitalForm(request.POST or None, instance=vital_instance, prefix="vitals")
    diagnosis_formset = DiagnosisFormSet(request.POST or None, instance=encounter, prefix="diagnosis")
    medication_formset = MedicationFormSet(request.POST or None, instance=encounter, prefix="medication")

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
        },
    )


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
