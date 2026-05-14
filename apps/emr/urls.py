from django.urls import path

from . import views

app_name = "emr"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("patients/search/", views.patient_search_view, name="patient_search"),
    path("patients/register/", views.patient_create_view, name="patient_create"),
    path("patients/<int:pk>/", views.patient_detail_view, name="patient_detail"),
    path("patients/<int:pk>/edit/", views.patient_edit_view, name="patient_edit"),
    path("patients/<int:patient_pk>/appointments/new/", views.appointment_create_view, name="appointment_create"),
    path("appointments/<int:pk>/status/", views.appointment_status_view, name="appointment_status"),
    path("appointments/<int:appointment_pk>/triage/", views.triage_view, name="triage"),
    path("patients/<int:patient_pk>/encounters/new/", views.encounter_create_view, name="encounter_create"),
    path(
        "patients/<int:patient_pk>/encounters/<int:encounter_pk>/",
        views.encounter_edit_view,
        name="encounter_edit",
    ),
    path("scribe/<int:session_pk>/attach/", views.scribe_intake_view, name="scribe_intake"),
    path("encounters/<int:encounter_pk>/referrals/new/", views.referral_create_view, name="referral_create"),
    path("encounters/<int:encounter_pk>/prescription/", views.prescription_print_view, name="prescription_print"),
    path("referrals/<int:referral_pk>/print/", views.referral_print_view, name="referral_print"),
    path("settings/", views.organisation_settings_view, name="settings"),
]
