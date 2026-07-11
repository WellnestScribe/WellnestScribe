from django.conf import settings
from django.db import models


class DoctorProfile(models.Model):
    """Per-doctor preferences. Drives prompt personalization + UI defaults."""

    SPECIALTY_CHOICES = [
        ("general", "General Practice"),
        ("internal", "Internal Medicine"),
        ("anesthesia", "Anesthesiology"),
        ("surgery", "Surgery"),
        ("obgyn", "Obstetrics & Gynecology"),
        ("pediatrics", "Pediatrics"),
        ("psychiatry", "Psychiatry"),
        ("neurology", "Neurology"),
        ("cardiology", "Cardiology"),
        ("emergency", "Emergency Medicine"),
        ("family", "Family Medicine"),
        ("other", "Other"),
    ]

    NOTE_STYLE_CHOICES = [
        ("soap", "SOAP (compartmentalized)"),
        ("narrative", "Narrative (free-form)"),
        ("chart", "Chart / progress note"),
    ]

    ROLE_CLINICIAN    = "clinician"
    ROLE_LEAD         = "lead"
    ROLE_ADMIN        = "admin"
    ROLE_SCRIBE       = "scribe"       # Medical scribe - record + view, cannot finalize
    ROLE_ED_NURSE     = "ed_nurse"     # ED nurse - ED board + triage access
    ROLE_NURSE        = "nurse"        # General nurse - view & assist, no finalize
    ROLE_RECEPTIONIST = "receptionist" # Reception - read-only session list
    ROLE_RADIOLOGIST  = "radiologist"  # Imaging - view + report, no finalize of clinical notes
    ROLE_PHARMACIST   = "pharmacist"   # Pharmacy - meds/prescriptions
    ROLE_LAB_TECH     = "lab_tech"     # Laboratory technician
    ROLE_CHOICES = [
        (ROLE_CLINICIAN,    "Doctor / Clinician"),
        (ROLE_LEAD,         "Clinical lead"),
        (ROLE_ADMIN,        "Administrator"),
        (ROLE_NURSE,        "Nurse"),
        (ROLE_ED_NURSE,     "ED nurse"),
        (ROLE_SCRIBE,       "Medical scribe"),
        (ROLE_RECEPTIONIST, "Receptionist"),
        (ROLE_RADIOLOGIST,  "Radiologist"),
        (ROLE_PHARMACIST,   "Pharmacist"),
        (ROLE_LAB_TECH,     "Lab technician"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )
    full_name = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=40, blank=True, default="Dr.")
    specialty = models.CharField(
        max_length=30, choices=SPECIALTY_CHOICES, default="general"
    )
    facility = models.CharField(max_length=120, blank=True)

    default_note_style = models.CharField(
        max_length=20, choices=NOTE_STYLE_CHOICES, default="soap"
    )
    long_form_default = models.BooleanField(default=False)
    suggestive_assist = models.BooleanField(default=False)
    font_scale = models.PositiveSmallIntegerField(default=100)
    theme = models.CharField(
        max_length=10,
        choices=[("light", "Light"), ("dark", "Dark"), ("auto", "System")],
        default="light",
    )

    custom_drugs = models.JSONField(
        default=list,
        blank=True,
        help_text="Doctor-specific medication names shown in the note editor picker.",
    )
    LANGUAGE_CHOICES = [
        ("jam_Latn", "Jamaican Creole (Patois)"),
        ("eng_Latn", "English"),
        ("spa_Latn", "Spanish"),
        ("fra_Latn", "French"),
        ("hat_Latn", "Haitian Creole"),
        ("por_Latn", "Portuguese"),
        ("wol_Latn", "Wolof"),
        ("kin_Latn", "Kinyarwanda"),
    ]

    preferred_language = models.CharField(
        max_length=20,
        choices=LANGUAGE_CHOICES,
        default="jam_Latn",
        help_text="Language spoken during consultations - used by the ASR model.",
    )
    custom_instructions = models.TextField(blank=True)
    custom_terms = models.TextField(
        blank=True,
        help_text=(
            "Regional or personal abbreviations, one per line. "
            "e.g. 'HTN = hypertension', 'SLE = systemic lupus erythematosus'. "
            "Added to every note-generation prompt."
        ),
    )

    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_CLINICIAN
    )

    # Login tracking - shown on the dashboard so doctors can spot unexpected access
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    previous_login_ip = models.GenericIPAddressField(null=True, blank=True)
    previous_login_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.title} {self.full_name or self.user.get_username()}".strip()

    @property
    def display_name(self) -> str:
        if self.full_name:
            return f"{self.title} {self.full_name}".strip()
        return self.user.get_username()

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN or self.user.is_staff or self.user.is_superuser

    @property
    def is_lead(self) -> bool:
        return self.is_admin or self.role == self.ROLE_LEAD

    def can_access_triage(self) -> bool:
        """Triage Lab access: admins, leads, or staff/superuser."""
        return self.is_lead

    def can_use_scribe(self) -> bool:
        """Can record sessions and generate notes."""
        return self.role in (
            self.ROLE_CLINICIAN, self.ROLE_LEAD, self.ROLE_ADMIN, self.ROLE_SCRIBE
        ) or self.user.is_staff or self.user.is_superuser

    def can_finalize(self) -> bool:
        """Can mark a note as clinically reviewed and lock it."""
        return self.role in (
            self.ROLE_CLINICIAN, self.ROLE_LEAD, self.ROLE_ADMIN
        ) or self.user.is_staff or self.user.is_superuser

    def can_use_ed_board(self) -> bool:
        """Can access Emergency Department board and triage."""
        return self.role in (
            self.ROLE_CLINICIAN, self.ROLE_LEAD, self.ROLE_ADMIN,
            self.ROLE_ED_NURSE, self.ROLE_NURSE,
        ) or self.user.is_staff or self.user.is_superuser

    def is_read_only(self) -> bool:
        """Receptionist: can view sessions list but not edit or generate."""
        return self.role == self.ROLE_RECEPTIONIST and not (
            self.user.is_staff or self.user.is_superuser
        )


class PlatformControl(models.Model):
    """Singleton global kill-switch for public demos.

    Lets an admin throttle or lock the platform for non-admin users - e.g. when
    sharing a sign-up QR with a room full of strangers and you need to stop a
    bad actor from burning model credits by hammering the pipeline. Admins are
    never affected, so your own live demo always works.

    There is exactly one row (pk=1). Read it with PlatformControl.get().
    """

    MODE_OFF     = "off"
    MODE_LIMITED = "limited"   # non-admins capped at note_limit sessions, then politely stopped
    MODE_LOCKED  = "locked"    # non-admins blocked from the whole app
    MODE_CHOICES = [
        (MODE_OFF,     "Off - normal operation"),
        (MODE_LIMITED, "Test mode - limit each non-admin to a few notes"),
        (MODE_LOCKED,  "Locked - block all non-admin usage"),
    ]

    DEFAULT_LIMITED_MESSAGE = (
        "Thanks for trying WellNest! This account has reached its trial limit "
        "for our preview. We'll be opening up full access soon."
    )
    DEFAULT_LOCKED_MESSAGE = (
        "WellNest is currently in test mode while our team applies some finishing "
        "touches. Please check back shortly - thanks for your patience."
    )

    demo_mode = models.CharField(
        max_length=10, choices=MODE_CHOICES, default=MODE_OFF
    )
    note_limit = models.PositiveSmallIntegerField(
        default=1,
        help_text="In Test mode, the max number of sessions a non-admin may create.",
    )
    message = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Optional override for the message non-admins see. Blank uses a sensible default.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "Platform control"
        verbose_name_plural = "Platform control"

    def __str__(self) -> str:
        return f"PlatformControl(demo_mode={self.demo_mode})"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    _CACHE_KEY = "platform_control_singleton"

    @classmethod
    def get(cls) -> "PlatformControl":
        # Cached briefly (per process) so the demo-lock middleware doesn't query
        # this singleton on EVERY request. Admin toggles take effect within ~30s;
        # save() invalidates it immediately on the process that changed it.
        from django.core.cache import cache
        obj = cache.get(cls._CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls._CACHE_KEY, obj, 30)
        return obj

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete(self._CACHE_KEY)

    @property
    def is_off(self) -> bool:
        return self.demo_mode == self.MODE_OFF

    def message_for_mode(self) -> str:
        if self.message.strip():
            return self.message.strip()
        if self.demo_mode == self.MODE_LIMITED:
            return self.DEFAULT_LIMITED_MESSAGE
        return self.DEFAULT_LOCKED_MESSAGE


def user_is_admin(user) -> bool:
    """True if user is a platform admin (role admin, staff, or superuser).

    Safe to call with anonymous users. Does not raise when no DoctorProfile
    exists, so it is usable from middleware on every request.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    profile = DoctorProfile.objects.filter(user=user).first()
    return bool(profile and profile.is_admin)
