from django.contrib import admin

from .models import DoctorProfile


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
