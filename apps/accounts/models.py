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

    ROLE_CLINICIAN = "clinician"
    ROLE_LEAD = "lead"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_CLINICIAN, "Clinician"),
        (ROLE_LEAD, "Clinical lead"),
        (ROLE_ADMIN, "Administrator"),
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

    custom_instructions = models.TextField(blank=True)

    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_CLINICIAN
    )

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
