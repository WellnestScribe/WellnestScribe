from django.contrib import admin

from .models import (
    Allergy,
    Appointment,
    AuditLog,
    Diagnosis,
    Encounter,
    Immunisation,
    Medication,
    Organisation,
    OrganisationMembership,
    Patient,
    Referral,
    Vital,
)


class AllergyInline(admin.TabularInline):
    model = Allergy
    extra = 0


class AppointmentInline(admin.TabularInline):
    model = Appointment
    extra = 0


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "organisation_type", "parish", "subscription_tier", "is_active")
    list_filter = ("organisation_type", "parish", "subscription_tier", "is_active")
    search_fields = ("name", "nhf_facility_code", "email")


@admin.register(OrganisationMembership)
class OrganisationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "role", "is_default", "created_at")
    list_filter = ("role", "is_default", "organisation")
    search_fields = ("user__username", "user__email", "organisation__name")
    list_editable = ("role", "is_default")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("display_name", "date_of_birth", "sex", "parish", "phone_primary", "nhf_card_number")
    list_filter = ("organisation", "sex", "parish", "language_preference")
    search_fields = (
        "legal_first_name",
        "legal_last_name",
        "preferred_name",
        "phone_primary",
        "nhf_card_number",
        "trn",
    )
    inlines = [AllergyInline, AppointmentInline]


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "scheduled_for", "encounter_type", "status", "queue_number")
    list_filter = ("organisation", "encounter_type", "status")
    search_fields = ("patient__legal_first_name", "patient__legal_last_name", "notes")


class DiagnosisInline(admin.TabularInline):
    model = Diagnosis
    extra = 0


class MedicationInline(admin.TabularInline):
    model = Medication
    extra = 0


@admin.register(Encounter)
class EncounterAdmin(admin.ModelAdmin):
    list_display = ("patient", "encounter_date", "encounter_type", "encounter_status", "provider")
    list_filter = ("organisation", "encounter_type", "encounter_status")
    search_fields = ("patient__legal_first_name", "patient__legal_last_name", "chief_complaint")
    inlines = [DiagnosisInline, MedicationInline]


@admin.register(Vital)
class VitalAdmin(admin.ModelAdmin):
    list_display = ("patient", "recorded_at", "bp_systolic", "bp_diastolic", "blood_glucose_mmol", "bmi")
    list_filter = ("organisation",)
    search_fields = ("patient__legal_first_name", "patient__legal_last_name")


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("patient", "receiving_facility", "urgency", "status", "referral_date")
    list_filter = ("organisation", "urgency", "status")
    search_fields = ("patient__legal_first_name", "patient__legal_last_name", "receiving_facility")


@admin.register(Immunisation)
class ImmunisationAdmin(admin.ModelAdmin):
    list_display = ("patient", "vaccine_name", "date_given", "dose_number", "next_due_date")
    list_filter = ("organisation", "vaccine_name")
    search_fields = ("patient__legal_first_name", "patient__legal_last_name", "vaccine_name")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organisation", "user", "action", "resource_type", "resource_id")
    list_filter = ("organisation", "action", "resource_type")
    search_fields = ("detail", "resource_id", "user__username", "organisation__name")
    readonly_fields = (
        "organisation",
        "user",
        "action",
        "resource_type",
        "resource_id",
        "ip_address",
        "user_agent",
        "detail",
        "changes",
        "created_at",
        "updated_at",
    )
