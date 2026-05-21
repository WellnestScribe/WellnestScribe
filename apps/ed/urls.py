from django.urls import path
from . import views

app_name = "ed"

urlpatterns = [
    # Redirect root
    path("", lambda request: __import__("django.shortcuts", fromlist=["redirect"]).redirect("ed:board"), name="index"),

    # Tracking board
    path("board/", views.TrackingBoardView.as_view(), name="board"),

    # Visit management
    path("visits/", views.VisitListView.as_view(), name="visit_list"),
    path("visits/new/", views.NewVisitView.as_view(), name="new_visit"),
    path("visits/<int:pk>/", views.VisitDetailView.as_view(), name="visit_detail"),
    path("visits/<int:pk>/triage/", views.TriageFormView.as_view(), name="triage_form"),
    path("visits/<int:pk>/physician/", views.PhysicianView.as_view(), name="physician_view"),
    path("visits/<int:pk>/zone/", views.zone_assign_view, name="zone_assign"),
    path("visits/<int:pk>/disposition/", views.DispositionView.as_view(), name="disposition"),

    # Shift management
    path("shifts/", views.ShiftListView.as_view(), name="shifts"),
    path("shifts/open/", views.ShiftOpenView.as_view(), name="shift_open"),
    path("shifts/<int:pk>/close/", views.shift_close_view, name="shift_close"),
    path("shifts/<int:pk>/handover/", views.HandoverView.as_view(), name="handover"),

    # AJAX API
    path("api/board/", views.board_json, name="api_board"),
    path("api/visits/<int:pk>/esi/", views.esi_ai_api, name="api_esi"),
    path("api/visits/<int:pk>/zone/", views.zone_assign_api, name="api_zone"),
    path("api/shifts/<int:pk>/handover/generate/", views.handover_generate_api, name="api_handover_generate"),
]
