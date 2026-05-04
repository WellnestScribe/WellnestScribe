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
    path(
        "api/preferences/",
        views.update_preferences_api,
        name="api_preferences",
    ),
]
