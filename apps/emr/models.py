"""Core EMR models.

This app is intentionally organisation-scoped and self-contained so a problem
inside the EMR cannot destabilize the scribe workflows. The only cross-app
relationship is the optional link from an encounter back to a `scribe` session.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models

from .constants import (
    ALLERGY_SEVERITY_CHOICES,
    ALLERGY_STATUS_CHOICES,
    ALLERGY_TYPE_CHOICES,
    APPOINTMENT_STATUS_CHOICES,
    CONSENT_METHOD_CHOICES,
    DIAGNOSIS_STATUS_CHOICES,
    ENCOUNTER_STATUS_CHOICES,
    ENCOUNTER_TYPE_CHOICES,
    IMMUNISATION_ROUTE_CHOICES,
    IMMUNISATION_SITE_CHOICES,
    LANGUAGE_CHOICES,
    MEDICATION_STATUS_CHOICES,
    MEMBERSHIP_ROLE_CHOICES,
    ORGANISATION_TYPE_CHOICES,
    PARISH_CHOICES,
    PATIENT_SEX_CHOICES,
    REFERRAL_STATUS_CHOICES,
    REFERRAL_URGENCY_CHOICES,
    ROUTE_CHOICES,
)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrganisationScopedModel(TimestampedModel):
    organisation = models.ForeignKey(
        "emr.Organisation",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    class Meta:
        abstract = True


class Organisation(TimestampedModel):
    name = models.CharField(max_length=200)
    organisation_type = models.CharField(
        max_length=40,
        choices=ORGANISATION_TYPE_CHOICES,
        default="private_clinic",
    )
    parish = models.CharField(max_length=50, choices=PARISH_CHOICES, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    nhf_facility_code = models.CharField(max_length=20, blank=True)
    subscription_tier = models.CharField(max_length=20, default="trial")
    subscription_status = models.CharField(max_length=20, default="active")
    billing_currency = models.CharField(max_length=3, default="JMD")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class OrganisationMembership(TimestampedModel):
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organisation_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=MEMBERSHIP_ROLE_CHOICES,
        default="doctor",
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ("organisation__name", "user__username")
        constraints = [
            models.UniqueConstraint(
                fields=("organisation", "user"),
                name="emr_unique_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organisation} ({self.role})"

    @property
    def is_admin(self) -> bool:
        return self.role in {"admin", "system_admin"}

    @property
    def is_doctor(self) -> bool:
        return self.role in {"doctor", "system_admin"}

    def can_register_patients(self) -> bool:
        return self.role in {"doctor", "nurse", "receptionist", "admin", "system_admin"}

    def can_record_vitals(self) -> bool:
        return self.role in {"doctor", "nurse", "system_admin"}

    def can_manage_schedule(self) -> bool:
        return self.role in {"doctor", "nurse", "receptionist", "admin", "system_admin"}

    def can_edit_encounters(self) -> bool:
        return self.role in {"doctor", "nurse", "system_admin"}

    def can_sign_encounters(self) -> bool:
        return self.role in {"doctor", "system_admin"}


class Patient(OrganisationScopedModel):
    legal_first_name = models.CharField(max_length=100)
    legal_last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField()
    sex = models.CharField(max_length=10, choices=PATIENT_SEX_CHOICES)
    gender_identity = models.CharField(max_length=50, blank=True)
    nhf_card_number = models.CharField(max_length=20, blank=True)
    trn = models.CharField(max_length=9, blank=True)
    nids_number = models.CharField(max_length=30, blank=True)
    street_address = models.TextField(blank=True)
    community = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    parish = models.CharField(max_length=50, choices=PARISH_CHOICES, blank=True)
    phone_primary = models.CharField(max_length=20, blank=True)
    phone_secondary = models.CharField(max_length=20, blank=True)
    phone_is_whatsapp = models.BooleanField(default=False)
    email = models.EmailField(blank=True)
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    next_of_kin_name = models.CharField(max_length=200, blank=True)
    next_of_kin_relationship = models.CharField(max_length=50, blank=True)
    nhf_card_programme = models.CharField(max_length=100, blank=True)
    private_insurer_name = models.CharField(max_length=100, blank=True)
    private_policy_number = models.CharField(max_length=50, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    ethnicity = models.CharField(max_length=50, blank=True)
    nationality = models.CharField(max_length=50, default="Jamaican", blank=True)
    language_preference = models.CharField(
        max_length=50,
        choices=LANGUAGE_CHOICES,
        default="English",
    )
    blood_group = models.CharField(max_length=5, blank=True)
    herbal_history = models.TextField(blank=True)
    consent_given = models.BooleanField(default=False)
    consent_date = models.DateTimeField(null=True, blank=True)
    consent_method = models.CharField(
        max_length=20,
        choices=CONSENT_METHOD_CHOICES,
        blank=True,
    )
    deceased = models.BooleanField(default=False)
    deceased_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_patients_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_patients_updated",
    )

    class Meta:
        ordering = ("legal_last_name", "legal_first_name", "date_of_birth")
        indexes = [
            models.Index(fields=("organisation", "legal_last_name", "legal_first_name")),
            models.Index(fields=("organisation", "nhf_card_number")),
            models.Index(fields=("organisation", "trn")),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.legal_first_name} {self.legal_last_name}".strip()

    @property
    def display_name(self) -> str:
        if self.preferred_name:
            return f"{self.preferred_name} ({self.full_name})"
        return self.full_name

    @property
    def age_display(self) -> str:
        from django.utils import timezone

        today = timezone.localdate()
        years = today.year - self.date_of_birth.year
        before_birthday = (today.month, today.day) < (
            self.date_of_birth.month,
            self.date_of_birth.day,
        )
        if before_birthday:
            years -= 1
        return str(max(years, 0))


class Allergy(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="allergies",
    )
    allergen_name = models.CharField(max_length=200)
    allergen_type = models.CharField(
        max_length=20,
        choices=ALLERGY_TYPE_CHOICES,
        blank=True,
    )
    reaction_type = models.CharField(max_length=200, blank=True)
    severity = models.CharField(
        max_length=20,
        choices=ALLERGY_SEVERITY_CHOICES,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=ALLERGY_STATUS_CHOICES,
        default="active",
    )
    onset_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("allergen_name",)

    def __str__(self) -> str:
        return f"{self.allergen_name} ({self.patient})"


class Appointment(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    scheduled_for = models.DateTimeField()
    encounter_type = models.CharField(
        max_length=40,
        choices=ENCOUNTER_TYPE_CHOICES,
        default="acute",
    )
    status = models.CharField(
        max_length=20,
        choices=APPOINTMENT_STATUS_CHOICES,
        default="scheduled",
    )
    queue_number = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_appointments_created",
    )

    class Meta:
        ordering = ("scheduled_for", "queue_number", "patient__legal_last_name")
        indexes = [models.Index(fields=("organisation", "scheduled_for", "status"))]

    def __str__(self) -> str:
        return f"{self.patient} @ {self.scheduled_for:%Y-%m-%d %H:%M}"


class Encounter(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="encounters",
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="emr_encounters",
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encounters",
    )
    encounter_date = models.DateField()
    encounter_time = models.TimeField(null=True, blank=True)
    encounter_type = models.CharField(
        max_length=40,
        choices=ENCOUNTER_TYPE_CHOICES,
        default="acute",
    )
    chief_complaint = models.TextField(blank=True)
    history_of_presenting_illness = models.TextField(blank=True)
    review_of_systems = models.TextField(blank=True)
    physical_examination = models.TextField(blank=True)
    assessment_notes = models.TextField(blank=True)
    plan_notes = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_instructions = models.TextField(blank=True)
    sick_leave_start = models.DateField(null=True, blank=True)
    sick_leave_end = models.DateField(null=True, blank=True)
    sick_leave_diagnosis = models.CharField(max_length=200, blank=True)
    herbal_remedies = models.TextField(blank=True)
    encounter_status = models.CharField(
        max_length=20,
        choices=ENCOUNTER_STATUS_CHOICES,
        default="draft",
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_encounters_signed",
    )
    amended_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="amendments",
    )
    scribe_session = models.ForeignKey(
        "scribe.ScribeSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_encounters",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_encounters_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_encounters_updated",
    )

    class Meta:
        ordering = ("-encounter_date", "-encounter_time", "-created_at")
        indexes = [
            models.Index(fields=("organisation", "patient", "encounter_date")),
            models.Index(fields=("organisation", "encounter_status", "encounter_date")),
        ]

    def __str__(self) -> str:
        return f"{self.patient} - {self.encounter_date:%Y-%m-%d}"


class Vital(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="vitals",
    )
    encounter = models.OneToOneField(
        Encounter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vitals",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_vitals_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    bmi = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bp_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_celsius = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    oxygen_saturation = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    blood_glucose_mmol = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    muac_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    head_circumference_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_for_age_percentile = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    height_for_age_percentile = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    bmi_for_age_percentile = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ("-recorded_at",)

    def __str__(self) -> str:
        return f"Vitals for {self.patient} @ {self.recorded_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        self.bmi = self._calculate_bmi()
        super().save(*args, **kwargs)

    def _calculate_bmi(self):
        if not self.weight_kg or not self.height_cm:
            return None
        try:
            height_m = Decimal(self.height_cm) / Decimal("100")
            if height_m <= 0:
                return None
            bmi = Decimal(self.weight_kg) / (height_m * height_m)
            return bmi.quantize(Decimal("0.1"))
        except (InvalidOperation, ZeroDivisionError):
            return None


class Diagnosis(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="diagnoses",
    )
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="diagnoses",
    )
    icd10_code = models.CharField(max_length=10)
    icd10_description = models.CharField(max_length=500, blank=True)
    snomed_code = models.CharField(max_length=20, blank=True)
    onset_date = models.DateField(null=True, blank=True)
    resolution_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DIAGNOSIS_STATUS_CHOICES,
        default="active",
    )
    diagnosis_rank = models.PositiveSmallIntegerField(default=1)
    diagnosing_provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_diagnoses_made",
    )
    notes = models.TextField(blank=True)
    ai_suggested = models.BooleanField(default=False)
    ai_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ("diagnosis_rank", "icd10_code")

    def __str__(self) -> str:
        return f"{self.icd10_code} - {self.patient}"


class Medication(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="medications",
    )
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="medications",
    )
    prescribing_provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_medications_prescribed",
    )
    drug_name_generic = models.CharField(max_length=200)
    drug_name_brand = models.CharField(max_length=200, blank=True)
    is_ven_listed = models.BooleanField(default=False)
    rxnorm_code = models.CharField(max_length=20, blank=True)
    dose_amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dose_unit = models.CharField(max_length=20, blank=True)
    route = models.CharField(max_length=50, choices=ROUTE_CHOICES, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    refills_authorised = models.PositiveSmallIntegerField(default=0)
    refills_remaining = models.PositiveSmallIntegerField(default=0)
    pharmacy_instructions = models.TextField(blank=True)
    interaction_flags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=MEDICATION_STATUS_CHOICES,
        default="active",
    )
    reason_discontinued = models.TextField(blank=True)
    ai_suggested = models.BooleanField(default=False)
    ai_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "drug_name_generic")

    def __str__(self) -> str:
        return f"{self.drug_name_generic} - {self.patient}"


class Referral(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="referrals",
    )
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="referrals",
    )
    referring_provider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_referrals_made",
    )
    receiving_facility = models.CharField(max_length=200)
    receiving_specialty = models.CharField(max_length=100, blank=True)
    urgency = models.CharField(
        max_length=20,
        choices=REFERRAL_URGENCY_CHOICES,
        default="routine",
    )
    reason = models.TextField()
    clinical_summary = models.TextField(blank=True)
    current_medications_snapshot = models.JSONField(default=list, blank=True)
    referral_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=REFERRAL_STATUS_CHOICES,
        default="draft",
    )
    response_notes = models.TextField(blank=True)
    response_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-referral_date", "-created_at")

    def __str__(self) -> str:
        return f"Referral for {self.patient} to {self.receiving_facility}"


class Immunisation(OrganisationScopedModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="immunisations",
    )
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="immunisations",
    )
    administered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_immunisations_administered",
    )
    vaccine_name = models.CharField(max_length=100)
    nip_schedule_code = models.CharField(max_length=20, blank=True)
    dose_number = models.PositiveSmallIntegerField(null=True, blank=True)
    date_given = models.DateField()
    batch_number = models.CharField(max_length=50, blank=True)
    site = models.CharField(max_length=50, choices=IMMUNISATION_SITE_CHOICES, blank=True)
    route = models.CharField(max_length=20, choices=IMMUNISATION_ROUTE_CHOICES, blank=True)
    next_due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-date_given", "vaccine_name")

    def __str__(self) -> str:
        return f"{self.vaccine_name} - {self.patient}"


class AuditLog(TimestampedModel):
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_audit_events",
    )
    action = models.CharField(max_length=50)
    resource_type = models.CharField(max_length=50, blank=True)
    resource_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    detail = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organisation", "created_at")),
            models.Index(fields=("resource_type", "resource_id")),
        ]

    def __str__(self) -> str:
        return f"{self.action} - {self.resource_type} {self.resource_id}"
