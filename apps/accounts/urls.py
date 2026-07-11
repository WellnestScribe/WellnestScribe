from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signin/", views.signin_view, name="signin"),
    path("signup/", views.signup_view, name="signup"),
    path("signout/", views.signout_view, name="signout"),
    path("password-help/", views.password_help_view, name="password_help"),
    path("profile/", views.profile_view, name="profile"),
    path("subscription/", views.subscription_view, name="subscription"),
    path("my-data/export/", views.my_data_export, name="my_data_export"),
    path("demo-control/", views.demo_control_api, name="demo_control"),
    path("bootstrap-admin/", views.bootstrap_admin_view, name="bootstrap_admin"),
    # Idle lock re-authentication
    path("api/reauth/", views.reauth_api, name="reauth_api"),
    # Custom drugs API (DB-backed, per-doctor)
    path("api/custom-drugs/", views.custom_drugs_api, name="custom_drugs_api"),
    # Users & Organisations admin panel
    path("users/", views.users_admin_view, name="users_admin"),
    path("billing/", views.billing_view, name="billing"),
    path("docs/", views.docs_view, name="docs"),
    path("docs/<slug:slug>/", views.docs_view, name="docs_page"),
    path("users/create/", views.create_user_api, name="create_user"),
    path("organisations/create/", views.create_organisation_api, name="create_organisation"),
    path("organisations/<int:org_id>/deactivate/", views.organisation_deactivate_api, name="organisation_deactivate"),
    path("organisations/<int:org_id>/restore/", views.organisation_restore_api, name="organisation_restore"),
    path("organisations/<int:org_id>/delete/", views.organisation_delete_api, name="organisation_delete"),
    path("organisations/<int:org_id>/export/", views.organisation_export_api, name="organisation_export"),
    path("users/<int:user_id>/role/", views.update_user_role_api, name="update_user_role"),
    path("users/<int:user_id>/set-password/", views.set_password_api, name="set_password"),
    path("users/<int:user_id>/toggle-active/", views.toggle_user_active_api, name="toggle_user_active"),
    path("users/membership/", views.update_membership_api, name="update_membership"),
]
