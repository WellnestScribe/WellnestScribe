from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import NoteShare, ScribeSession, SessionEvent, SOAPNote


class SessionEventInline(admin.TabularInline):
    model = SessionEvent
    extra = 0
    readonly_fields = ("event_type", "detail", "created_at")
    can_delete = False
    ordering = ("-created_at",)


@admin.register(ScribeSession)
class ScribeSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "doctor",
        "title_short",
        "note_format",
        "length_mode",
        "status",
        "event_count",
        "created_at",
    )
    list_filter = ("status", "note_format", "length_mode", "session_type", "doctor")
    search_fields = ("title", "chief_complaint", "doctor__username", "doctor__email")
    date_hierarchy = "created_at"
    inlines = [SessionEventInline]
    readonly_fields = ("created_at", "updated_at", "finalized_at")

    @admin.display(description="title")
    def title_short(self, obj):
        return obj.display_title[:80]

    @admin.display(description="events")
    def event_count(self, obj):
        return obj._event_count if hasattr(obj, "_event_count") else obj.events.count()

    def get_queryset(self, request):
        qs = super().get_queryset(request).annotate(_event_count=Count("events"))
        return qs


@admin.register(SOAPNote)
class SOAPNoteAdmin(admin.ModelAdmin):
    list_display = ("session", "review_completed", "export_count", "updated_at")
    list_filter = ("review_completed",)
    search_fields = ("session__title", "session__doctor__username")


@admin.register(SessionEvent)
class SessionEventAdmin(admin.ModelAdmin):
    list_display = ("session_link", "event_type", "doctor_username", "detail_short", "created_at")
    list_filter = ("event_type", "session__doctor")
    search_fields = ("detail", "session__doctor__username", "session__title")
    date_hierarchy = "created_at"
    readonly_fields = ("session", "event_type", "detail", "created_at")

    @admin.display(description="session")
    def session_link(self, obj):
        url = reverse("admin:scribe_scribesession_change", args=[obj.session_id])
        return format_html('<a href="{}">#{}</a>', url, obj.session_id)

    @admin.display(description="doctor")
    def doctor_username(self, obj):
        return obj.session.doctor.username if obj.session_id else ""

    @admin.display(description="detail")
    def detail_short(self, obj):
        return (obj.detail or "")[:80]


@admin.register(NoteShare)
class NoteShareAdmin(admin.ModelAdmin):
    list_display = ("session", "expires_at", "opened_count", "created_at")
    list_filter = ("created_at",)
    search_fields = ("token", "session__title")
    readonly_fields = ("token", "expires_at", "opened_count", "created_at")
