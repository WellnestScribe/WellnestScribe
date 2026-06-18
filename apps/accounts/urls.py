from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signin/", views.signin_view, name="signin"),
    path("signup/", views.signup_view, name="signup"),
    path("signout/", views.signout_view, name="signout"),
    path("profile/", views.profile_view, name="profile"),
    path("bootstrap-admin/", views.bootstrap_admin_view, name="bootstrap_admin"),
    # Idle lock re-authentication
    path("api/reauth/", views.reauth_api, name="reauth_api"),
    # Custom drugs API (DB-backed, per-doctor)
    path("api/custom-drugs/", views.custom_drugs_api, name="custom_drugs_api"),
    # Users & Organisations admin panel
    path("users/", views.users_admin_view, name="users_admin"),
    path("users/create/", views.create_user_api, name="create_user"),
    path("users/<int:user_id>/role/", views.update_user_role_api, name="update_user_role"),
    path("users/<int:user_id>/set-password/", views.set_password_api, name="set_password"),
    path("users/<int:user_id>/toggle-active/", views.toggle_user_active_api, name="toggle_user_active"),
    path("users/membership/", views.update_membership_api, name="update_membership"),
]
