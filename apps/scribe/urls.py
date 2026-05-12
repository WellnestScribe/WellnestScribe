from django.urls import path

from . import views

app_name = "scribe"

urlpatterns = [
    path("", views.RecordView.as_view(), name="record"),
    path("sessions/", views.HistoryView.as_view(), name="history"),
    path("sessions/<int:pk>/review/", views.ReviewView.as_view(), name="review"),
    path("sessions/<int:pk>/", views.SessionDetailView.as_view(), name="detail"),

    # API endpoints used by the JS recorder + editor
    path("api/sessions/", views.create_session_api, name="api_create"),
    path(
        "api/sessions/<int:pk>/transcribe/",
        views.transcribe_session_api,
        name="api_transcribe",
    ),
    path(
        "api/sessions/<int:pk>/generate/",
        views.generate_note_api,
        name="api_generate",
    ),
    path(
        "api/sessions/<int:pk>/save/",
        views.save_note_api,
        name="api_save",
    ),
    path(
        "api/sessions/<int:pk>/finalize/",
        views.finalize_session_api,
        name="api_finalize",
    ),
    path(
        "api/sessions/<int:pk>/share/",
        views.share_note_api,
        name="api_share",
    ),
    path("share/<str:token>/", views.share_view, name="share"),
    path("api/quick-transcribe/", views.quick_transcribe_api, name="api_quick_transcribe"),
    path("triage/", views.TriageView.as_view(), name="triage"),
    path("audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("compliance/", views.ComplianceView.as_view(), name="compliance"),
    path("api/triage/run/", views.triage_run_api, name="api_triage_run"),
    path("api/triage/jobs/<str:job_id>/", views.triage_job_status_api, name="api_triage_job"),
    path("api/triage/interpret/", views.triage_interpret_api, name="api_triage_interpret"),
    path("api/triage/download/", views.triage_download_api, name="api_triage_download"),
    path("api/triage/probe/", views.triage_probe_api, name="api_triage_probe"),
    path("api/triage/install/", views.triage_install_deps_api, name="api_triage_install"),
    path("api/triage/install-audio/", views.triage_install_audio_api, name="api_triage_install_audio"),
    path(
        "api/sessions/<int:pk>/improve/",
        views.suggest_improvements_api,
        name="api_improve",
    ),
    path(
        "api/sessions/<int:pk>/polish/",
        views.polish_note_api,
        name="api_polish",
    ),
    path(
        "api/preferences/",
        views.update_preferences_api,
        name="api_preferences",
    ),
]
