from django.urls import path

from . import views

app_name = "emr"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("api/queue/", views.waiting_queue_api, name="api_queue"),
    path("api/patient-search/", views.patient_search_api, name="api_patient_search"),
    path("appointments/", views.appointments_calendar_view, name="appointments"),
    path("api/appointments/feed/", views.appointments_feed_api, name="api_appointments_feed"),
    path("api/appointments/book/", views.appointment_book_api, name="api_appointment_book"),
    path("api/appointments/due/", views.appointments_due_api, name="api_appointments_due"),
    path("patients/search/", views.patient_search_view, name="patient_search"),
    path("patients/register/", views.patient_create_view, name="patient_create"),
    path("patients/<int:pk>/", views.patient_detail_view, name="patient_detail"),
    path("patients/<int:patient_pk>/activity/", views.patient_activity_api, name="patient_activity"),
    path("patients/<int:pk>/edit/", views.patient_edit_view, name="patient_edit"),
    path("patients/<int:patient_pk>/intake/", views.intake_view, name="intake"),
    path("patients/<int:patient_pk>/add-to-queue/", views.patient_add_to_queue_view, name="add_to_queue"),
    path("patients/<int:patient_pk>/appointments/new/", views.appointment_create_view, name="appointment_create"),
    path("appointments/<int:pk>/status/", views.appointment_status_view, name="appointment_status"),
    path("appointments/<int:pk>/reorder/", views.appointment_reorder_view, name="appointment_reorder"),
    path("appointments/<int:pk>/delete/", views.appointment_delete_view, name="appointment_delete"),
    path("worklist/close-day/", views.worklist_close_day_view, name="worklist_close_day"),
    path("appointments/<int:appointment_pk>/triage/", views.triage_view, name="triage"),
    path("patients/<int:patient_pk>/encounters/new/", views.encounter_create_view, name="encounter_create"),
    path(
        "patients/<int:patient_pk>/encounters/<int:encounter_pk>/",
        views.encounter_edit_view,
        name="encounter_edit",
    ),
    path(
        "patients/<int:patient_pk>/encounters/<int:encounter_pk>/view/",
        views.encounter_view,
        name="encounter_view",
    ),
    path("scribe/<int:session_pk>/attach/", views.scribe_intake_view, name="scribe_intake"),
    path("scribe/<int:session_pk>/link/", views.scribe_link_patient_view, name="scribe_link"),
    path("encounters/<int:encounter_pk>/addendum/", views.encounter_addendum_view, name="encounter_addendum"),
    path("encounters/<int:encounter_pk>/referrals/new/", views.referral_create_view, name="referral_create"),
    path("encounters/<int:encounter_pk>/prescription/", views.prescription_print_view, name="prescription_print"),
    path("referrals/<int:referral_pk>/print/", views.referral_print_view, name="referral_print"),
    path("settings/", views.organisation_settings_view, name="settings"),

    # ── GNU Health / external EMR bridge ──────────────────────────────────────
    path("api/gnuhealth/status/", views.gnuhealth_status_api, name="api_gnuhealth_status"),
    path("api/gnuhealth/patients/", views.gnuhealth_patient_search_api, name="api_gnuhealth_patients"),
    path(
        "api/gnuhealth/sessions/<int:session_pk>/push/",
        views.gnuhealth_push_session_api,
        name="api_gnuhealth_push",
    ),
]
