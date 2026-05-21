"""Forms for the Emergency Department workflow."""

from django import forms
from django.utils import timezone

from .models import (
    DispositionRecord,
    EDShift,
    EDVisit,
    ShiftHandoverNote,
    TriageAssessment,
    ARRIVAL_MODE_CHOICES,
    ZONE_CHOICES,
)


class BootstrapMixin:
    """Add Bootstrap classes to every field widget automatically."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            cls = w.attrs.get("class", "")
            if isinstance(w, (forms.Select, forms.SelectMultiple)):
                if "form-select" not in cls:
                    w.attrs["class"] = (cls + " form-select").strip()
            elif isinstance(w, forms.CheckboxInput):
                if "form-check-input" not in cls:
                    w.attrs["class"] = (cls + " form-check-input").strip()
            elif not isinstance(w, (forms.HiddenInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                if "form-control" not in cls:
                    w.attrs["class"] = (cls + " form-control").strip()


class NewVisitForm(BootstrapMixin, forms.ModelForm):
    """Registration clerk / triage nurse creates a new ED visit."""

    patient_name_unregistered = forms.CharField(
        max_length=200,
        required=False,
        label="Patient name (if not in EMR)",
        widget=forms.TextInput(attrs={"placeholder": "John Doe — fill if not found in EMR search"}),
    )

    class Meta:
        model = EDVisit
        fields = [
            "patient_name_unregistered",
            "arrival_mode",
            "ambulance_crew",
            "referring_facility",
            "ems_handover_notes",
            "arrived_at",
        ]
        widgets = {
            "arrival_mode": forms.Select(attrs={"class": "form-select"}),
            "arrived_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "ems_handover_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime(timezone.now())
        self.fields["arrived_at"].initial = now.strftime("%Y-%m-%dT%H:%M")


class TriageAssessmentForm(BootstrapMixin, forms.ModelForm):
    """Full triage nurse assessment form."""

    class Meta:
        model = TriageAssessment
        exclude = [
            "visit",
            "assessed_by",
            "assessed_at",
            "ai_esi_suggestion",
            "ai_esi_rationale",
            "ai_esi_flags",
            "created_at",
            "updated_at",
        ]
        widgets = {
            "chief_complaint": forms.TextInput(
                attrs={"placeholder": "e.g. Chest pain, severe headache, road traffic accident"}
            ),
            "complaint_onset": forms.Select(attrs={"class": "form-select"}),
            "mechanism": forms.Select(attrs={"class": "form-select"}),
            "trauma_details": forms.Textarea(attrs={"rows": 2}),
            "esi_score": forms.RadioSelect(),
            "esi_override_reason": forms.Textarea(attrs={"rows": 2}),
            "temp_celsius": forms.NumberInput(attrs={"step": "0.1", "placeholder": "e.g. 37.2"}),
            "bp_systolic": forms.NumberInput(attrs={"placeholder": "120"}),
            "bp_diastolic": forms.NumberInput(attrs={"placeholder": "80"}),
            "pulse_bpm": forms.NumberInput(attrs={"placeholder": "72"}),
            "rr_rpm": forms.NumberInput(attrs={"placeholder": "16"}),
            "spo2_percent": forms.NumberInput(attrs={"step": "0.1", "placeholder": "98"}),
            "weight_kg": forms.NumberInput(attrs={"step": "0.1", "placeholder": "70"}),
            "pain_score": forms.NumberInput(attrs={"min": 0, "max": 10, "placeholder": "0–10"}),
            "blood_glucose_mmol": forms.NumberInput(attrs={"step": "0.1", "placeholder": "5.5"}),
            "gcs_eye": forms.Select(
                choices=[("", "—")] + [(i, f"{i}") for i in range(1, 5)],
                attrs={"class": "form-select"},
            ),
            "gcs_verbal": forms.Select(
                choices=[("", "—")] + [(i, f"{i}") for i in range(1, 6)],
                attrs={"class": "form-select"},
            ),
            "gcs_motor": forms.Select(
                choices=[("", "—")] + [(i, f"{i}") for i in range(1, 7)],
                attrs={"class": "form-select"},
            ),
            "allergies": forms.TextInput(attrs={"placeholder": "e.g. Penicillin (anaphylaxis), Ibuprofen (rash)"}),
            "pmh_other": forms.TextInput(attrs={"placeholder": "Other relevant history"}),
            "current_medications": forms.Textarea(attrs={"rows": 3, "placeholder": "List current medications"}),
            "last_oral_intake": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "pregnant": forms.Select(attrs={"class": "form-select"}),
            "lmp": forms.DateInput(attrs={"type": "date"}),
            "triage_notes": forms.Textarea(attrs={"rows": 3}),
            "re_triage_reason": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_pain_score(self):
        val = self.cleaned_data.get("pain_score")
        if val is not None and not (0 <= val <= 10):
            raise forms.ValidationError("Pain score must be 0–10.")
        return val

    def clean_gcs_eye(self):
        val = self.cleaned_data.get("gcs_eye")
        if val is not None and not (1 <= val <= 4):
            raise forms.ValidationError("GCS Eye must be 1–4.")
        return val

    def clean_gcs_verbal(self):
        val = self.cleaned_data.get("gcs_verbal")
        if val is not None and not (1 <= val <= 5):
            raise forms.ValidationError("GCS Verbal must be 1–5.")
        return val

    def clean_gcs_motor(self):
        val = self.cleaned_data.get("gcs_motor")
        if val is not None and not (1 <= val <= 6):
            raise forms.ValidationError("GCS Motor must be 1–6.")
        return val


class ZoneAssignForm(BootstrapMixin, forms.Form):
    """Quick zone reassignment (used from board or visit detail)."""

    zone = forms.ChoiceField(choices=ZONE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    bed_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. A3, Resus-1"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Reason for move (optional)"}),
    )


class DispositionForm(BootstrapMixin, forms.ModelForm):
    """Physician finalizes visit disposition."""

    class Meta:
        model = DispositionRecord
        exclude = ["visit", "decided_by", "decided_at", "created_at"]
        widgets = {
            "disposition": forms.Select(attrs={"class": "form-select"}),
            "ward_admitted_to": forms.TextInput(attrs={"placeholder": "e.g. Medical Ward B"}),
            "transfer_facility": forms.TextInput(attrs={"placeholder": "Receiving hospital name"}),
            "transfer_reason": forms.Textarea(attrs={"rows": 2}),
            "discharge_instructions": forms.Textarea(attrs={"rows": 4}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
            "follow_up_with": forms.TextInput(attrs={"placeholder": "e.g. Cardiologist, GP, Orthopaedics"}),
            "prescriptions_issued": forms.Textarea(attrs={"rows": 3}),
            "referrals_made": forms.Textarea(attrs={"rows": 2}),
            "disposition_notes": forms.Textarea(attrs={"rows": 3}),
            "cause_of_death": forms.TextInput(attrs={"placeholder": "If applicable"}),
        }


class ShiftOpenForm(BootstrapMixin, forms.ModelForm):
    """Open a new shift."""

    class Meta:
        model = EDShift
        fields = ["shift_type", "shift_date", "incoming_notes"]
        widgets = {
            "shift_type": forms.Select(attrs={"class": "form-select"}),
            "shift_date": forms.DateInput(attrs={"type": "date"}),
            "incoming_notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Any notes from incoming team briefing"}
            ),
        }


class HandoverNoteForm(BootstrapMixin, forms.ModelForm):
    """Edit a single SBAR note for a patient."""

    class Meta:
        model = ShiftHandoverNote
        fields = ["situation", "background", "assessment", "recommendation"]
        widgets = {
            "situation": forms.Textarea(attrs={"rows": 2}),
            "background": forms.Textarea(attrs={"rows": 2}),
            "assessment": forms.Textarea(attrs={"rows": 2}),
            "recommendation": forms.Textarea(attrs={"rows": 2}),
        }
