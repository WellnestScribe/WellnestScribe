from django.contrib import admin

from .models import DoctorProfile


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "specialty", "facility", "default_note_style")
    list_filter = ("specialty", "default_note_style", "theme")
    search_fields = ("user__username", "full_name", "facility")
