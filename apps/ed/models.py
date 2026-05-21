"""Emergency Department models.

Structured around the Mercer General ED workflow:
  Arrival → Triage → Zone → Physician → Disposition → Exit

Five mandatory timestamps per visit drive LOS metrics and MoH reporting.
"""

from __future__ import annotations

import datetime
from django.conf import settings
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Choice sets
# ---------------------------------------------------------------------------

ARRIVAL_MODE_CHOICES = [
    ("walk_in", "Walk-in"),
    ("ambulance", "Ambulance"),
    ("wheelchair", "Wheelchair"),
    ("police_escort", "Police escort"),
    ("brought_by_relative", "Brought by relative"),
    ("transferred", "Transferred from facility"),
    ("self_referral", "Self-referral (GP letter)"),
]

VISIT_STATUS_CHOICES = [
    ("arrived", "Arrived – awaiting triage"),
    ("triaged", "Triaged – awaiting zone"),
    ("in_zone", "In zone – awaiting doctor"),
    ("with_doctor", "With doctor"),
    ("disposition_pending", "Disposition pending"),
    ("discharged", "Discharged"),
    ("admitted", "Admitted"),
    ("transferred", "Transferred"),
    ("absconded", "Absconded"),
    ("deceased", "Deceased"),
]

ZONE_CHOICES = [
    ("resus", "Resuscitation"),
    ("acute", "Acute"),
    ("observation", "Short-stay Observation"),
    ("fast_track", "Fast-track"),
    ("isolation", "Isolation"),
    ("waiting", "Waiting room"),
]

ESI_CHOICES = [
    (1, "ESI 1 — Immediate"),
    (2, "ESI 2 — Emergent"),
    (3, "ESI 3 — Urgent"),
    (4, "ESI 4 — Less Urgent"),
    (5, "ESI 5 — Non-urgent"),
]

MECHANISM_CHOICES = [
    ("medical", "Medical"),
    ("blunt_trauma", "Blunt trauma"),
    ("penetrating_trauma", "Penetrating trauma"),
    ("burn", "Burn"),
    ("fall", "Fall"),
    ("mva", "Motor vehicle accident"),
    ("drowning", "Drowning / near-drowning"),
    ("poisoning", "Poisoning / overdose"),
    ("unknown", "Unknown"),
]

COMPLAINT_ONSET_CHOICES = [
    ("minutes", "Minutes"),
    ("hours", "Hours"),
    ("days", "Days"),
    ("weeks", "Weeks"),
    ("months", "Months"),
]

PREGNANT_CHOICES = [
    ("yes", "Yes"),
    ("no", "No"),
    ("unknown", "Unknown / not asked"),
    ("na", "Not applicable"),
]

DISPOSITION_CHOICES = [
    ("discharge_home", "DH — Discharge home"),
    ("admit_general", "AW — Admit: general ward"),
    ("admit_icu", "AI — Admit: ICU"),
    ("admit_hdu", "AH — Admit: HDU"),
    ("admit_paeds", "AP — Admit: paediatric ward"),
    ("admit_maternity", "AM — Admit: maternity"),
    ("transfer", "TR — Transfer to facility"),
    ("dama", "DA — Discharged against medical advice"),
    ("absconded", "AB — Absconded"),
    ("deceased", "DC — Deceased"),
]

SHIFT_TYPE_CHOICES = [
    ("day", "Day (07:00 – 15:00)"),
    ("evening", "Evening (15:00 – 23:00)"),
    ("night", "Night (23:00 – 07:00)"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_visit_number() -> str:
    today = datetime.date.today()
    prefix = today.strftime("ED-%Y%m%d-")
    count = EDVisit.objects.filter(arrived_at__date=today).count() + 1
    return f"{prefix}{count:03d}"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EDVisit(models.Model):
    """Core ED encounter record. One per patient visit."""

    organisation = models.ForeignKey(
        "emr.Organisation",
        on_delete=models.CASCADE,
        related_name="ed_visits",
    )
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_visits",
    )
    patient_name_unregistered = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name used before patient is linked to EMR record.",
    )
    visit_number = models.CharField(max_length=20, unique=True, blank=True)

    # -- 5 mandatory timestamps ---
    arrived_at = models.DateTimeField(default=timezone.now)
    triaged_at = models.DateTimeField(null=True, blank=True)
    seen_by_doctor_at = models.DateTimeField(null=True, blank=True)
    disposition_decided_at = models.DateTimeField(null=True, blank=True)
    exited_at = models.DateTimeField(null=True, blank=True)

    # -- Arrival ---
    arrival_mode = models.CharField(
        max_length=30,
        choices=ARRIVAL_MODE_CHOICES,
        default="walk_in",
    )
    ambulance_crew = models.CharField(max_length=200, blank=True)
    referring_facility = models.CharField(max_length=200, blank=True)
    ems_handover_notes = models.TextField(blank=True)

    # -- Status & zone ---
    current_status = models.CharField(
        max_length=30,
        choices=VISIT_STATUS_CHOICES,
        default="arrived",
    )
    current_zone = models.CharField(
        max_length=20,
        choices=ZONE_CHOICES,
        default="waiting",
    )
    current_bed = models.CharField(max_length=20, blank=True)
    zone_assigned_at = models.DateTimeField(null=True, blank=True)

    # -- Team ---
    triage_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_triage_visits",
    )
    charge_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_charge_visits",
    )
    attending_physician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_physician_visits",
    )

    # -- EMR link ---
    emr_encounter = models.OneToOneField(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_visit",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_visits_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-arrived_at",)
        indexes = [
            models.Index(fields=("organisation", "current_status", "arrived_at")),
            models.Index(fields=("organisation", "current_zone")),
        ]

    def __str__(self) -> str:
        return f"{self.visit_number} — {self.display_name}"

    def save(self, *args, **kwargs):
        if not self.visit_number:
            self.visit_number = _generate_visit_number()
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        if self.patient:
            return self.patient.full_name
        return self.patient_name_unregistered or "Unknown patient"

    @property
    def esi_score(self) -> int | None:
        try:
            return self.triage.esi_score
        except TriageAssessment.DoesNotExist:
            return None

    @property
    def chief_complaint(self) -> str:
        try:
            return self.triage.chief_complaint
        except TriageAssessment.DoesNotExist:
            return ""

    @property
    def time_in_department_minutes(self) -> int:
        end = self.exited_at or timezone.now()
        return int((end - self.arrived_at).total_seconds() / 60)

    @property
    def door_to_triage_minutes(self) -> int | None:
        if self.triaged_at:
            return int((self.triaged_at - self.arrived_at).total_seconds() / 60)
        return None

    @property
    def door_to_doctor_minutes(self) -> int | None:
        if self.seen_by_doctor_at:
            return int((self.seen_by_doctor_at - self.arrived_at).total_seconds() / 60)
        return None

    @property
    def is_active(self) -> bool:
        return self.current_status not in {
            "discharged", "admitted", "transferred", "absconded", "deceased"
        }

    @property
    def esi_color_class(self) -> str:
        return {
            1: "danger",
            2: "warning",
            3: "primary",
            4: "success",
            5: "info",
        }.get(self.esi_score, "secondary")

    @property
    def zone_color_class(self) -> str:
        return {
            "resus": "danger",
            "acute": "warning",
            "observation": "primary",
            "fast_track": "success",
            "isolation": "purple",
            "waiting": "secondary",
        }.get(self.current_zone, "secondary")


class TriageAssessment(models.Model):
    """Triage nurse's full assessment. One-to-one with EDVisit."""

    visit = models.OneToOneField(
        EDVisit,
        on_delete=models.CASCADE,
        related_name="triage",
    )
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_triage_assessments",
    )
    assessed_at = models.DateTimeField(default=timezone.now)

    # -- Presenting problem ---
    chief_complaint = models.CharField(max_length=300)
    complaint_onset = models.CharField(
        max_length=20,
        choices=COMPLAINT_ONSET_CHOICES,
        blank=True,
    )
    complaint_duration = models.CharField(max_length=100, blank=True)
    mechanism = models.CharField(
        max_length=30,
        choices=MECHANISM_CHOICES,
        default="medical",
    )
    trauma_details = models.TextField(blank=True)

    # -- ESI ---
    esi_score = models.PositiveSmallIntegerField(choices=ESI_CHOICES)
    ai_esi_suggestion = models.PositiveSmallIntegerField(
        choices=ESI_CHOICES,
        null=True,
        blank=True,
    )
    ai_esi_rationale = models.TextField(blank=True)
    ai_esi_flags = models.JSONField(default=list, blank=True)
    esi_override_reason = models.TextField(blank=True)

    # -- Vitals ---
    temp_celsius = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bp_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    rr_rpm = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2_percent = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_glucose_mmol = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    gcs_eye = models.PositiveSmallIntegerField(null=True, blank=True)
    gcs_verbal = models.PositiveSmallIntegerField(null=True, blank=True)
    gcs_motor = models.PositiveSmallIntegerField(null=True, blank=True)

    # -- History ---
    allergy_nkda = models.BooleanField(default=False)
    allergies = models.TextField(blank=True)
    pmh_htn = models.BooleanField(default=False)
    pmh_dm = models.BooleanField(default=False)
    pmh_asthma = models.BooleanField(default=False)
    pmh_cardiac = models.BooleanField(default=False)
    pmh_renal = models.BooleanField(default=False)
    pmh_hiv = models.BooleanField(default=False)
    pmh_sickle_cell = models.BooleanField(default=False)
    pmh_stroke = models.BooleanField(default=False)
    pmh_other = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    last_oral_intake = models.DateTimeField(null=True, blank=True)
    pregnant = models.CharField(
        max_length=10,
        choices=PREGNANT_CHOICES,
        default="na",
    )
    lmp = models.DateField(null=True, blank=True)

    # -- Notes ---
    triage_notes = models.TextField(blank=True)
    re_triage = models.BooleanField(default=False)
    re_triage_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-assessed_at",)

    def __str__(self) -> str:
        return f"Triage: {self.visit} (ESI {self.esi_score})"

    @property
    def gcs_total(self) -> int | None:
        if self.gcs_eye and self.gcs_verbal and self.gcs_motor:
            return self.gcs_eye + self.gcs_verbal + self.gcs_motor
        return None

    @property
    def has_critical_vitals(self) -> bool:
        checks = [
            self.pulse_bpm and (self.pulse_bpm > 130 or self.pulse_bpm < 40),
            self.bp_systolic and (self.bp_systolic < 90 or self.bp_systolic > 220),
            self.rr_rpm and (self.rr_rpm > 30 or self.rr_rpm < 8),
            self.spo2_percent and self.spo2_percent < 90,
            self.temp_celsius and (self.temp_celsius > 39.5 or self.temp_celsius < 35),
            self.gcs_total and self.gcs_total < 14,
        ]
        return any(checks)

    @property
    def pmh_list(self) -> list[str]:
        mapping = {
            "pmh_htn": "HTN",
            "pmh_dm": "DM",
            "pmh_asthma": "Asthma",
            "pmh_cardiac": "Cardiac disease",
            "pmh_renal": "Renal disease",
            "pmh_hiv": "HIV",
            "pmh_sickle_cell": "Sickle cell",
            "pmh_stroke": "Stroke/TIA",
        }
        result = [label for field, label in mapping.items() if getattr(self, field)]
        if self.pmh_other:
            result.append(self.pmh_other)
        return result

    @property
    def vital_flags(self) -> list[str]:
        flags = []
        if self.pulse_bpm and self.pulse_bpm > 130:
            flags.append(f"Tachycardia HR {self.pulse_bpm}")
        if self.pulse_bpm and self.pulse_bpm < 40:
            flags.append(f"Bradycardia HR {self.pulse_bpm}")
        if self.bp_systolic and self.bp_systolic < 90:
            flags.append(f"Hypotension SBP {self.bp_systolic}")
        if self.bp_systolic and self.bp_systolic > 220:
            flags.append(f"Hypertensive crisis SBP {self.bp_systolic}")
        if self.rr_rpm and self.rr_rpm > 30:
            flags.append(f"Tachypnoea RR {self.rr_rpm}")
        if self.spo2_percent and self.spo2_percent < 90:
            flags.append(f"Hypoxia SpO₂ {self.spo2_percent}%")
        if self.temp_celsius and self.temp_celsius > 39.5:
            flags.append(f"High fever {self.temp_celsius}°C")
        if self.temp_celsius and self.temp_celsius < 35:
            flags.append(f"Hypothermia {self.temp_celsius}°C")
        if self.gcs_total and self.gcs_total < 14:
            flags.append(f"Reduced GCS {self.gcs_total}/15")
        return flags


class ZoneAssignment(models.Model):
    """Tracks every zone movement for a visit. Full audit trail."""

    visit = models.ForeignKey(
        EDVisit,
        on_delete=models.CASCADE,
        related_name="zone_history",
    )
    zone = models.CharField(max_length=20, choices=ZONE_CHOICES)
    bed_number = models.CharField(max_length=20, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_zone_assignments",
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-assigned_at",)

    def __str__(self) -> str:
        return f"{self.visit.visit_number} → {self.get_zone_display()}"


class DispositionRecord(models.Model):
    """Final disposition decision. One-to-one with EDVisit."""

    visit = models.OneToOneField(
        EDVisit,
        on_delete=models.CASCADE,
        related_name="disposition",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_dispositions",
    )
    decided_at = models.DateTimeField(default=timezone.now)

    disposition = models.CharField(max_length=30, choices=DISPOSITION_CHOICES)
    ward_admitted_to = models.CharField(max_length=100, blank=True)
    transfer_facility = models.CharField(max_length=200, blank=True)
    transfer_reason = models.TextField(blank=True)

    discharge_instructions = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_with = models.CharField(max_length=200, blank=True)
    prescriptions_issued = models.TextField(blank=True)
    referrals_made = models.TextField(blank=True)
    disposition_notes = models.TextField(blank=True)
    cause_of_death = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.visit.visit_number} → {self.get_disposition_display()}"


class EDShift(models.Model):
    """Shift record for the department. Opens at shift start, closes at handover."""

    organisation = models.ForeignKey(
        "emr.Organisation",
        on_delete=models.CASCADE,
        related_name="ed_shifts",
    )
    shift_type = models.CharField(max_length=10, choices=SHIFT_TYPE_CHOICES)
    shift_date = models.DateField()
    charge_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_shifts_charge",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_shifts_opened",
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_shifts_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    incoming_notes = models.TextField(blank=True)
    census_at_close = models.PositiveSmallIntegerField(null=True, blank=True)
    critical_flags = models.TextField(blank=True)

    class Meta:
        ordering = ("-shift_date", "shift_type")
        constraints = [
            models.UniqueConstraint(
                fields=("organisation", "shift_date", "shift_type"),
                name="ed_unique_shift_per_day",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_shift_type_display()} — {self.shift_date}"

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class ShiftHandoverNote(models.Model):
    """Per-patient SBAR handover note generated at shift change."""

    outgoing_shift = models.ForeignKey(
        EDShift,
        on_delete=models.CASCADE,
        related_name="handover_notes",
    )
    visit = models.ForeignKey(
        EDVisit,
        on_delete=models.CASCADE,
        related_name="handover_notes",
    )
    situation = models.TextField(blank=True)
    background = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    ai_generated = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ed_handover_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("visit__current_zone", "visit__arrived_at")
        constraints = [
            models.UniqueConstraint(
                fields=("outgoing_shift", "visit"),
                name="ed_unique_handover_per_visit_shift",
            )
        ]

    def __str__(self) -> str:
        return f"Handover {self.outgoing_shift} — {self.visit.visit_number}"
