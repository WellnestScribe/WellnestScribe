from django.conf import settings
from django.db import models


class ScribeSession(models.Model):
    """One audio capture + the resulting note. Lifecycle owner of a recording."""

    SESSION_TYPE_CHOICES = [
        ("dictation", "Post-encounter dictation"),
        ("ambient", "Ambient recording"),
        ("text", "Direct text entry"),
    ]
    NOTE_FORMAT_CHOICES = [
        ("soap", "SOAP (compartmentalized)"),
        ("narrative", "Narrative (free-form)"),
        ("chart", "Chart / progress note"),
    ]
    LENGTH_MODE_CHOICES = [
        ("normal", "Normal"),
        ("long_form", "Long form"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("recording", "Recording"),
        ("transcribing", "Transcribing"),
        ("generating", "Generating note"),
        ("review", "Ready for review"),
        ("finalized", "Finalized"),
        ("error", "Error"),
    ]

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scribe_sessions",
    )
    title = models.CharField(max_length=160, blank=True)
    chief_complaint = models.CharField(max_length=200, blank=True)

    # Patient identity capture (Dr Elizabeth feedback — avoid mix-ups when
    # seeing many patients per day). Identifier can be DOB, hospital number,
    # ID number, or any free-text token doctor wants. Pilot rule: keep these
    # optional; if PILOT_MODE is on we discourage capturing real names.
    patient_name = models.CharField(max_length=120, blank=True)
    patient_identifier = models.CharField(max_length=120, blank=True)

    # Active conditions (multi-select checklist on record screen). Stored
    # as a comma-separated list of short keys: 'dm', 'htn', 'lipids',
    # 'ckd', 'obesity', etc.
    active_conditions = models.CharField(max_length=200, blank=True)

    audio_file = models.FileField(
        upload_to="scribe_audio/%Y/%m/%d/", null=True, blank=True
    )
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    session_type = models.CharField(
        max_length=20, choices=SESSION_TYPE_CHOICES, default="dictation"
    )
    note_format = models.CharField(
        max_length=20, choices=NOTE_FORMAT_CHOICES, default="soap"
    )
    length_mode = models.CharField(
        max_length=20, choices=LENGTH_MODE_CHOICES, default="normal"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    error_message = models.TextField(blank=True)

    transcript = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title or f"Session {self.pk}"

    @property
    def display_title(self) -> str:
        bits = []
        if self.patient_name:
            bits.append(self.patient_name)
        if self.patient_identifier:
            bits.append(f"({self.patient_identifier})")
        if self.title:
            bits.append(self.title)
        elif self.chief_complaint:
            bits.append(self.chief_complaint)
        if not bits:
            return f"Session {self.created_at.strftime('%b %d, %Y %I:%M %p')}"
        return " · ".join(bits)

    @property
    def conditions_list(self) -> list[str]:
        return [c for c in (self.active_conditions or "").split(",") if c.strip()]


class SOAPNote(models.Model):
    """Structured note attached to a session. Holds compartmentalized + narrative views."""

    session = models.OneToOneField(
        ScribeSession, on_delete=models.CASCADE, related_name="note"
    )

    subjective = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)

    narrative = models.TextField(blank=True)
    full_note = models.TextField(blank=True)
    edited_note = models.TextField(blank=True)

    flags = models.JSONField(default=list, blank=True)

    # Body diagram annotations — Dr Elizabeth feedback + NATVNS wound chart
    # adaptation. Each marker is a dict with these optional fields:
    #   x, y           : 0..100, percent of image (survives resizing)
    #   label          : short tooltip
    #   wound_type     : leg_ulcer | surgical | diabetic | pressure | other
    #   duration       : "3 weeks" / free text
    #   length_cm, width_cm, depth_cm, tracking_cm
    #   tissue_necrotic, tissue_slough, tissue_granulating,
    #   tissue_epithelialising, tissue_hypergranulating,
    #   tissue_haematoma, tissue_bone_tendon   (percent, totals 100%)
    #   exudate        : dry | wet | saturated  (severity)
    #   exudate_type   : serous | haemoserous | cloudy | green_brown
    #   peri_wound     : list of tags (macerated, oedematous, erythema,
    #                    excoriated, fragile, dry_scaly, healthy)
    #   infection_signs: list of tags (heat, new_slough, increasing_pain,
    #                    increasing_exudate, increasing_odour, friable)
    #   treatment_goal : debridement | absorption | hydration | protection |
    #                    palliative | reduce_bacterial_load
    #   analgesia      : regular | predressing | none
    #   notes          : free text
    # Old marker dicts (just size_cm + exudate + notes) still load fine —
    # missing keys are treated as blank.
    body_markers = models.JSONField(default=list, blank=True)

    # Top-level NATVNS fields that apply to the whole patient, not per-wound:
    #   factors_delaying_healing : list of codes
    #   allergies                : free text
    wound_chart = models.JSONField(default=dict, blank=True)

    review_completed = models.BooleanField(default=False)
    export_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Note for {self.session}"

    @property
    def display_text(self) -> str:
        return self.edited_note or self.full_note or self.narrative


class NoteShare(models.Model):
    """Short-lived public link to a note. Used for the phone→desktop QR flow."""

    session = models.ForeignKey(
        ScribeSession, on_delete=models.CASCADE, related_name="shares"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    opened_count = models.PositiveIntegerField(default=0)

    def is_valid(self) -> bool:
        from django.utils import timezone as _tz
        return _tz.now() < self.expires_at

    def __str__(self) -> str:
        return f"Share for {self.session_id} (until {self.expires_at:%Y-%m-%d %H:%M})"


class SessionEvent(models.Model):
    """Lightweight audit log entry per session. Useful for debugging + pilot."""

    EVENT_CHOICES = [
        ("created", "Session created"),
        ("uploaded", "Audio uploaded"),
        ("transcribed", "Transcription complete"),
        ("generated", "Note generated"),
        ("verified", "Note verified"),
        ("edited", "Doctor edited"),
        ("exported", "Exported"),
        ("finalized", "Finalized"),
        ("error", "Error"),
    ]

    session = models.ForeignKey(
        ScribeSession, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}"
