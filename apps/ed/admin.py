from django.contrib import admin
from .models import (
    DispositionRecord,
    EDShift,
    EDVisit,
    ShiftHandoverNote,
    TriageAssessment,
    ZoneAssignment,
)


class TriageInline(admin.StackedInline):
    model = TriageAssessment
    extra = 0
    readonly_fields = ("assessed_at", "ai_esi_suggestion", "ai_esi_rationale", "ai_esi_flags")


class ZoneHistoryInline(admin.TabularInline):
    model = ZoneAssignment
    extra = 0
    readonly_fields = ("assigned_at",)


class DispositionInline(admin.StackedInline):
    model = DispositionRecord
    extra = 0
    readonly_fields = ("decided_at",)


@admin.register(EDVisit)
class EDVisitAdmin(admin.ModelAdmin):
    list_display = (
        "visit_number",
        "display_name",
        "current_status",
        "current_zone",
        "esi_score",
        "arrived_at",
        "triage_nurse",
        "attending_physician",
    )
    list_filter = ("current_status", "current_zone", "arrival_mode", "organisation")
    search_fields = (
        "visit_number",
        "patient_name_unregistered",
        "patient__legal_first_name",
        "patient__legal_last_name",
    )
    readonly_fields = (
        "visit_number",
        "arrived_at",
        "triaged_at",
        "seen_by_doctor_at",
        "disposition_decided_at",
        "exited_at",
        "created_at",
        "updated_at",
    )
    inlines = [TriageInline, ZoneHistoryInline, DispositionInline]
    date_hierarchy = "arrived_at"

    def esi_score(self, obj):
        return obj.esi_score
    esi_score.short_description = "ESI"


@admin.register(EDShift)
class EDShiftAdmin(admin.ModelAdmin):
    list_display = ("shift_date", "shift_type", "charge_nurse", "opened_at", "closed_at", "is_open")
    list_filter = ("shift_type", "organisation")
    date_hierarchy = "shift_date"

    def is_open(self, obj):
        return obj.is_open
    is_open.boolean = True
    is_open.short_description = "Open"


@admin.register(ShiftHandoverNote)
class ShiftHandoverNoteAdmin(admin.ModelAdmin):
    list_display = ("outgoing_shift", "visit", "ai_generated", "created_at")
    list_filter = ("ai_generated", "outgoing_shift__shift_type")
    readonly_fields = ("created_at", "updated_at")
