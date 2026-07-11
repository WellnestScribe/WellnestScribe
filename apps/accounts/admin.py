from django.contrib import admin

from .models import DoctorProfile, PlatformControl


@admin.register(PlatformControl)
class PlatformControlAdmin(admin.ModelAdmin):
    list_display = ("demo_mode", "note_limit", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")

    def has_add_permission(self, request):
        # Singleton — created on first access via PlatformControl.get().
        return not PlatformControl.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "full_name",
        "role",
        "specialty",
        "facility",
        "default_note_style",
        "suggestive_assist",
    )
    list_filter = ("role", "specialty", "default_note_style", "suggestive_assist", "theme")
    search_fields = ("user__username", "user__email", "full_name", "facility")
    list_editable = ("role",)
    fieldsets = (
        (None, {"fields": ("user", "title", "full_name", "specialty", "facility")}),
        ("Access control", {"fields": ("role",)}),
        ("Note preferences", {
            "fields": (
                "default_note_style",
                "long_form_default",
                "suggestive_assist",
                "custom_instructions",
            )
        }),
        ("Display", {"fields": ("font_scale", "theme")}),
    )
