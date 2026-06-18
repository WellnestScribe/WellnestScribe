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
    path("api/sessions/<int:pk>/rename/", views.rename_session_api, name="api_rename"),
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
        "api/sessions/<int:pk>/generate/stream/",
        views.generate_note_stream_api,
        name="api_generate_stream",
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
    path(
        "api/sessions/<int:pk>/delete/",
        views.delete_session_api,
        name="api_delete",
    ),
    path("share/<str:token>/", views.share_view, name="share"),
    # QR claim — authenticated phone landing page (fires SSE event to PC)
    path("claim/<str:token>/", views.phone_claim_view, name="phone_claim"),
    # SSE stream — PC listens here for QR scan notifications
    path("scan-events/", views.scan_events_view, name="scan_events"),
    path("api/patients/", views.patients_api, name="api_patients"),
    path("api/quick-transcribe/", views.quick_transcribe_api, name="api_quick_transcribe"),
    path(
        "api/sessions/<int:pk>/resume/",
        views.resume_session_api,
        name="api_resume",
    ),
    path("triage/", views.TriageView.as_view(), name="triage"),
    path("drug-check/", views.DrugCheckView.as_view(), name="drug_check"),
    path("api/drug-check/", views.drug_check_api, name="api_drug_check"),
    path("api/drug-search/", views.drug_search_api, name="api_drug_search"),
    path("api/herb-search/", views.herb_search_api, name="api_herb_search"),
    path("audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("latency/", views.LatencyLogView.as_view(), name="latency_log"),
    path("feedback/", views.FeedbackLogView.as_view(), name="feedback_log"),
    path("api/sessions/<int:pk>/rate/", views.rate_section_api, name="api_rate_section"),
    path("compliance/", views.ComplianceView.as_view(), name="compliance"),
    path("api/triage/run/", views.triage_run_api, name="api_triage_run"),
    path("api/triage/jobs/<str:job_id>/", views.triage_job_status_api, name="api_triage_job"),
    path("api/triage/interpret/", views.triage_interpret_api, name="api_triage_interpret"),
    path(
        "api/triage/extract-demographics/",
        views.triage_extract_demographics_api,
        name="api_triage_extract_demographics",
    ),
    path("api/triage/download/", views.triage_download_api, name="api_triage_download"),
    path("api/triage/probe/", views.triage_probe_api, name="api_triage_probe"),
    path("api/triage/install/", views.triage_install_deps_api, name="api_triage_install"),
    path("api/triage/install-audio/", views.triage_install_audio_api, name="api_triage_install_audio"),
    path("admin/modal-endpoints/", views.ModalEndpointsView.as_view(), name="modal_endpoints"),
    path("api/admin/modal-endpoints/", views.modal_endpoint_add_api, name="api_modal_endpoint_add"),
    path("api/admin/modal-endpoints/validate/", views.modal_endpoint_validate_api, name="api_modal_endpoint_validate"),
    path("api/admin/modal-endpoints/<int:pk>/delete/", views.modal_endpoint_delete_api, name="api_modal_endpoint_delete"),
    path("api/admin/modal-endpoints/<int:pk>/toggle/", views.modal_endpoint_toggle_api, name="api_modal_endpoint_toggle"),
    path("api/admin/modal-endpoints/<int:pk>/update/", views.modal_endpoint_update_api, name="api_modal_endpoint_update"),
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
        "api/sessions/<int:pk>/magic-edit/",
        views.magic_edit_api,
        name="api_magic_edit",
    ),
    path(
        "api/preferences/",
        views.update_preferences_api,
        name="api_preferences",
    ),
    path(
        "api/sessions/<int:pk>/ambient-transcribe/",
        views.ambient_transcribe_api,
        name="api_ambient_transcribe",
    ),
    path(
        "api/ambient-jobs/<str:job_id>/",
        views.ambient_job_api,
        name="api_ambient_job",
    ),
]
