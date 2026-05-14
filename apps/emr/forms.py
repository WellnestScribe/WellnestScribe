"""EMR forms and formsets."""

from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from .constants import COMMON_DRUGS, COMMON_ICD10_CODES
from .models import (
    Allergy,
    Appointment,
    Diagnosis,
    Encounter,
    Medication,
    Organisation,
    Patient,
    Referral,
    Vital,
)


class BootstrapModelForm(forms.ModelForm):
    """Applies Bootstrap classes consistently to text, select, and checkbox widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class PatientForm(BootstrapModelForm):
    class Meta:
        model = Patient
        fields = [
            "legal_first_name",
            "legal_last_name",
            "preferred_name",
            "date_of_birth",
            "sex",
            "gender_identity",
            "nhf_card_number",
            "trn",
            "nids_number",
            "street_address",
            "community",
            "district",
            "parish",
            "phone_primary",
            "phone_secondary",
            "phone_is_whatsapp",
            "email",
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_contact_phone",
            "next_of_kin_name",
            "next_of_kin_relationship",
            "nhf_card_programme",
            "private_insurer_name",
            "private_policy_number",
            "occupation",
            "ethnicity",
            "nationality",
            "language_preference",
            "blood_group",
            "herbal_history",
            "consent_given",
            "consent_date",
            "consent_method",
            "deceased",
            "deceased_date",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "street_address": forms.Textarea(attrs={"rows": 2}),
            "herbal_history": forms.Textarea(attrs={"rows": 3}),
            "consent_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "deceased_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("deceased") and not cleaned.get("deceased_date"):
            self.add_error("deceased_date", "Add the date of death when marking a patient deceased.")
        if cleaned.get("consent_given") and not cleaned.get("consent_method"):
            self.add_error("consent_method", "Choose how consent was captured.")
        return cleaned


class AllergyForm(BootstrapModelForm):
    class Meta:
        model = Allergy
        fields = [
            "allergen_name",
            "allergen_type",
            "reaction_type",
            "severity",
            "status",
            "onset_date",
            "notes",
        ]
        widgets = {
            "onset_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class AppointmentForm(BootstrapModelForm):
    class Meta:
        model = Appointment
        fields = ["scheduled_for", "encounter_type", "status", "queue_number", "notes"]
        widgets = {
            "scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_scheduled_for(self):
        scheduled_for = self.cleaned_data["scheduled_for"]
        if scheduled_for and timezone.is_naive(scheduled_for):
            scheduled_for = timezone.make_aware(scheduled_for)
        return scheduled_for


class EncounterForm(BootstrapModelForm):
    class Meta:
        model = Encounter
        fields = [
            "appointment",
            "provider",
            "encounter_date",
            "encounter_time",
            "encounter_type",
            "chief_complaint",
            "history_of_presenting_illness",
            "review_of_systems",
            "physical_examination",
            "assessment_notes",
            "plan_notes",
            "follow_up_date",
            "follow_up_instructions",
            "sick_leave_start",
            "sick_leave_end",
            "sick_leave_diagnosis",
            "herbal_remedies",
            "scribe_session",
        ]
        widgets = {
            "encounter_date": forms.DateInput(attrs={"type": "date"}),
            "encounter_time": forms.TimeInput(attrs={"type": "time"}),
            "chief_complaint": forms.Textarea(attrs={"rows": 2}),
            "history_of_presenting_illness": forms.Textarea(attrs={"rows": 4}),
            "review_of_systems": forms.Textarea(attrs={"rows": 3}),
            "physical_examination": forms.Textarea(attrs={"rows": 4}),
            "assessment_notes": forms.Textarea(attrs={"rows": 3}),
            "plan_notes": forms.Textarea(attrs={"rows": 4}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
            "follow_up_instructions": forms.Textarea(attrs={"rows": 2}),
            "sick_leave_start": forms.DateInput(attrs={"type": "date"}),
            "sick_leave_end": forms.DateInput(attrs={"type": "date"}),
            "herbal_remedies": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        organisation = kwargs.pop("organisation", None)
        provider_queryset = kwargs.pop("provider_queryset", None)
        scribe_queryset = kwargs.pop("scribe_queryset", None)
        super().__init__(*args, **kwargs)
        if organisation is not None:
            self.fields["appointment"].queryset = organisation.appointments.order_by("-scheduled_for")
        if provider_queryset is not None:
            self.fields["provider"].queryset = provider_queryset
        if scribe_queryset is not None:
            self.fields["scribe_session"].queryset = scribe_queryset
        self.fields["appointment"].required = False
        self.fields["scribe_session"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("sick_leave_end") and cleaned.get("sick_leave_start"):
            if cleaned["sick_leave_end"] < cleaned["sick_leave_start"]:
                self.add_error("sick_leave_end", "Sick leave end cannot be before the start date.")
        return cleaned


class VitalForm(BootstrapModelForm):
    class Meta:
        model = Vital
        fields = [
            "weight_kg",
            "height_cm",
            "bp_systolic",
            "bp_diastolic",
            "pulse_bpm",
            "respiratory_rate",
            "temperature_celsius",
            "oxygen_saturation",
            "blood_glucose_mmol",
            "muac_cm",
            "pain_score",
            "head_circumference_cm",
            "weight_for_age_percentile",
            "height_for_age_percentile",
            "bmi_for_age_percentile",
        ]

    def clean_pain_score(self):
        pain_score = self.cleaned_data.get("pain_score")
        if pain_score is not None and pain_score > 10:
            raise forms.ValidationError("Pain score must be between 0 and 10.")
        return pain_score


class DiagnosisForm(BootstrapModelForm):
    class Meta:
        model = Diagnosis
        fields = [
            "icd10_code",
            "icd10_description",
            "status",
            "diagnosis_rank",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["icd10_code"].widget.attrs.update(
            {
                "list": "emr-icd10-catalog",
                "placeholder": "I10",
            }
        )


class MedicationForm(BootstrapModelForm):
    class Meta:
        model = Medication
        fields = [
            "drug_name_generic",
            "drug_name_brand",
            "dose_amount",
            "dose_unit",
            "route",
            "frequency",
            "duration_days",
            "pharmacy_instructions",
        ]
        widgets = {"pharmacy_instructions": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug_name_generic"].widget.attrs.update(
            {
                "list": "emr-drug-catalog",
                "placeholder": "Amlodipine",
            }
        )
        self.fields["drug_name_brand"].widget.attrs.setdefault("placeholder", "Optional local brand")


class ReferralForm(BootstrapModelForm):
    class Meta:
        model = Referral
        fields = [
            "receiving_facility",
            "receiving_specialty",
            "urgency",
            "reason",
            "clinical_summary",
            "referral_date",
            "status",
        ]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
            "clinical_summary": forms.Textarea(attrs={"rows": 4}),
            "referral_date": forms.DateInput(attrs={"type": "date"}),
        }


class OrganisationForm(BootstrapModelForm):
    class Meta:
        model = Organisation
        fields = [
            "name",
            "organisation_type",
            "parish",
            "address",
            "phone",
            "email",
            "nhf_facility_code",
            "subscription_tier",
            "subscription_status",
            "billing_currency",
            "is_active",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }


def diagnosis_formset_class(*, extra_forms: int = 2):
    return inlineformset_factory(
        Encounter,
        Diagnosis,
        form=DiagnosisForm,
        extra=max(2, extra_forms),
        can_delete=True,
    )


def medication_formset_class(*, extra_forms: int = 3):
    return inlineformset_factory(
        Encounter,
        Medication,
        form=MedicationForm,
        extra=max(3, extra_forms),
        can_delete=True,
    )


DiagnosisFormSet = diagnosis_formset_class()
MedicationFormSet = medication_formset_class()


def common_code_catalog():
    return COMMON_ICD10_CODES


def common_drug_catalog():
    return COMMON_DRUGS
