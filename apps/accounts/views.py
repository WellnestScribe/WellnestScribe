import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .forms import DoctorProfileForm, WellnestSignInForm, WellnestSignUpForm
from .models import DoctorProfile


def _get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _no_admins_exist() -> bool:
    """True when no superuser/staff and no admin-role profile exists.

    Used to surface the 'first-run bootstrap' offer on the profile page.
    Once anyone is admin, this returns False and the offer disappears.
    """
    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        return False
    if User.objects.filter(is_staff=True).exists():
        return False
    if DoctorProfile.objects.filter(role=DoctorProfile.ROLE_ADMIN).exists():
        return False
    return True


@require_http_methods(["GET", "POST"])
def signin_view(request):
    if request.user.is_authenticated:
        return redirect("scribe:record")

    form = WellnestSignInForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        # Record login IP so the doctor can see it on the dashboard
        try:
            profile, _ = DoctorProfile.objects.get_or_create(user=user)
            ip = _get_client_ip(request)
            # Shift current → previous before overwriting
            profile.previous_login_ip = profile.last_login_ip
            profile.previous_login_at = profile.last_login_at
            profile.last_login_ip = ip or None
            profile.last_login_at = timezone.now()
            profile.save(update_fields=[
                "last_login_ip", "last_login_at",
                "previous_login_ip", "previous_login_at",
            ])
        except Exception:  # noqa: BLE001
            pass
        return redirect(request.GET.get("next") or reverse("scribe:record"))

    return render(request, "accounts/signin.html", {"form": form})


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("scribe:record")

    form = WellnestSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        DoctorProfile.objects.create(
            user=user,
            full_name=form.cleaned_data["full_name"],
            specialty=form.cleaned_data["specialty"],
            facility=form.cleaned_data.get("facility", ""),
        )
        # With multiple AUTHENTICATION_BACKENDS configured Django requires
        # an explicit backend on programmatic login.
        login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        return redirect("scribe:record")

    return render(request, "accounts/signup.html", {"form": form})


def signout_view(request):
    logout(request)
    return redirect("accounts:signin")


@login_required
@require_POST
@csrf_protect
def reauth_api(request):
    """Validate the current user's password without altering the session.

    Used by the client-side idle lock screen so the doctor can unlock the app
    without a full sign-out / sign-in cycle.  Returns 200 {"ok": true} on
    success, 401 {"ok": false} on wrong password.
    """
    try:
        payload = json.loads(request.body)
    except Exception:  # noqa: BLE001
        return JsonResponse({"ok": False, "error": "Bad request."}, status=400)

    password = (payload.get("password") or "").strip()
    if not password:
        return JsonResponse({"ok": False, "error": "Password required."}, status=400)

    user = authenticate(request, username=request.user.username, password=password)
    if user is not None and user.pk == request.user.pk:
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False, "error": "Incorrect password."}, status=401)


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
    form = DoctorProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "profile": profile,
            "bootstrap_admin_available": _no_admins_exist(),
        },
    )


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def custom_drugs_api(request):
    """GET → list; POST body {name} → add; DELETE body {name} → remove."""
    profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
    if request.method == "GET":
        return JsonResponse({"drugs": profile.custom_drugs or []})

    try:
        body = json.loads(request.body)
        name = (body.get("name") or "").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)

    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    drugs = list(profile.custom_drugs or [])
    if request.method == "POST":
        if not any(d.lower() == name.lower() for d in drugs):
            drugs.append(name)
    elif request.method == "DELETE":
        drugs = [d for d in drugs if d != name]

    profile.custom_drugs = drugs
    profile.save(update_fields=["custom_drugs"])
    return JsonResponse({"drugs": drugs})


def _require_admin(view_fn):
    """Decorator: allow access only to admin-role or staff users."""
    from functools import wraps

    @wraps(view_fn)
    def _inner(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/signin/?next={request.path}")
        profile = getattr(request.user, "doctor_profile", None)
        if not (profile and profile.is_admin):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Admin access required.")
        return view_fn(request, *args, **kwargs)

    return _inner


@require_http_methods(["GET"])
def users_admin_view(request):
    """Admin panel: list all users + organisations with role management.

    Accessible to system admins (full access) and org-level admins (restricted
    to their own org's users and organisations).
    """
    if not request.user.is_authenticated:
        return redirect(f"/accounts/signin/?next={request.path}")

    from emr.models import Organisation, OrganisationMembership
    from django.db.models import Q

    User = get_user_model()
    profile = getattr(request.user, "doctor_profile", None)
    is_system_admin = bool(profile and profile.is_admin)

    # Determine which orgs this user can manage
    if is_system_admin:
        managed_org_ids = set(Organisation.objects.values_list("pk", flat=True))
    else:
        managed_org_ids = set(
            OrganisationMembership.objects.filter(
                user=request.user, role__in=["admin", "system_admin"]
            ).values_list("organisation_id", flat=True)
        )

    if not (is_system_admin or managed_org_ids):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Admin or Organization Admin access required.")

    q = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "")
    status_filter = request.GET.get("status", "")

    users_qs = User.objects.select_related("doctor_profile").order_by("date_joined")
    # Org admins only see users who belong to their org(s)
    if not is_system_admin:
        users_qs = users_qs.filter(
            memberships__organisation_id__in=managed_org_ids
        ).distinct()

    if q:
        users_qs = users_qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(doctor_profile__full_name__icontains=q)
        ).distinct()
    if role_filter:
        users_qs = users_qs.filter(doctor_profile__role=role_filter)
    if status_filter == "active":
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == "inactive":
        users_qs = users_qs.filter(is_active=False)

    organisations = Organisation.objects.prefetch_related(
        "memberships__user__doctor_profile"
    ).order_by("name")
    if not is_system_admin:
        organisations = organisations.filter(pk__in=managed_org_ids)

    memberships_by_user = {}
    for m in OrganisationMembership.objects.select_related("organisation").all():
        memberships_by_user.setdefault(m.user_id, []).append(m)

    users_with_orgs = [(u, memberships_by_user.get(u.pk, [])) for u in users_qs]

    return render(request, "accounts/users_admin.html", {
        "users": users_qs,
        "users_with_orgs": users_with_orgs,
        "organisations": organisations,
        "role_choices": DoctorProfile.ROLE_CHOICES,
        "specialty_choices": DoctorProfile.SPECIALTY_CHOICES,
        "q": q,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "is_system_admin": is_system_admin,
        "managed_org_ids": managed_org_ids,
    })


@_require_admin
@require_POST
@csrf_protect
def create_user_api(request):
    """AJAX: admin creates a new user + DoctorProfile."""
    User = get_user_model()
    try:
        body = json.loads(request.body)
        username  = (body.get("username") or "").strip()
        email     = (body.get("email") or "").strip()
        full_name = (body.get("full_name") or "").strip()
        password  = (body.get("password") or "").strip()
        role      = (body.get("role") or DoctorProfile.ROLE_CLINICIAN).strip()
        specialty = (body.get("specialty") or "general").strip()
        facility  = (body.get("facility") or "").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)

    if not username or not password:
        return JsonResponse({"error": "Username and password are required."}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": f"Username '{username}' is already taken."}, status=400)
    if email and User.objects.filter(email=email).exists():
        return JsonResponse({"error": f"Email '{email}' is already registered."}, status=400)

    valid_roles = {r[0] for r in DoctorProfile.ROLE_CHOICES}
    if role not in valid_roles:
        role = DoctorProfile.ROLE_CLINICIAN

    user = User.objects.create_user(username=username, email=email, password=password)
    profile = DoctorProfile.objects.create(
        user=user, full_name=full_name, role=role,
        specialty=specialty, facility=facility,
    )
    return JsonResponse({
        "ok": True,
        "user_id": user.pk,
        "display_name": profile.display_name,
        "email": user.email,
        "role": profile.role,
        "role_label": dict(DoctorProfile.ROLE_CHOICES)[profile.role],
    })


@_require_admin
@require_POST
@csrf_protect
def update_user_role_api(request, user_id):
    """AJAX: change a user's DoctorProfile role."""
    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    try:
        body = json.loads(request.body)
        new_role = body.get("role", "").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)

    valid_roles = {r[0] for r in DoctorProfile.ROLE_CHOICES}
    if new_role not in valid_roles:
        return JsonResponse({"error": "invalid role"}, status=400)

    profile, _ = DoctorProfile.objects.get_or_create(user=target_user)
    profile.role = new_role
    profile.save(update_fields=["role"])
    return JsonResponse({"ok": True, "role": new_role, "role_label": dict(DoctorProfile.ROLE_CHOICES)[new_role]})


@require_POST
@csrf_protect
def update_membership_api(request):
    """AJAX: add/update or remove an OrganisationMembership.

    Accessible to system admins and org-level admins (for their own org only).
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "not authenticated"}, status=403)

    from emr.models import Organisation, OrganisationMembership

    User = get_user_model()
    try:
        body = json.loads(request.body)
        action  = body.get("action", "")
        user_id = body.get("user_id")
        org_id  = body.get("org_id")
        role    = body.get("role", "doctor")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)

    user = get_object_or_404(User, pk=user_id)
    org  = get_object_or_404(Organisation, pk=org_id)

    req_profile = getattr(request.user, "doctor_profile", None)
    is_sys_admin = bool(req_profile and req_profile.is_admin)
    if not is_sys_admin:
        is_org_admin = OrganisationMembership.objects.filter(
            user=request.user, organisation=org, role__in=["admin", "system_admin"]
        ).exists()
        if not is_org_admin:
            return JsonResponse({"error": "Permission denied."}, status=403)

    if action == "add":
        membership, _ = OrganisationMembership.objects.get_or_create(
            user=user, organisation=org, defaults={"role": role}
        )
        membership.role = role
        membership.save(update_fields=["role"])
        return JsonResponse({"ok": True})
    elif action == "remove":
        OrganisationMembership.objects.filter(user=user, organisation=org).delete()
        return JsonResponse({"ok": True})
    elif action == "update_role":
        OrganisationMembership.objects.filter(user=user, organisation=org).update(role=role)
        return JsonResponse({"ok": True})
    return JsonResponse({"error": "unknown action"}, status=400)


@_require_admin
@require_POST
@csrf_protect
def set_password_api(request, user_id):
    """AJAX: admin sets a new password for any user."""
    User = get_user_model()
    target = get_object_or_404(User, pk=user_id)
    try:
        body = json.loads(request.body)
        new_password = (body.get("new_password") or "").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    if len(new_password) < 6:
        return JsonResponse({"error": "Password must be at least 6 characters."}, status=400)
    target.set_password(new_password)
    target.save(update_fields=["password"])
    return JsonResponse({"ok": True})


@_require_admin
@require_POST
@csrf_protect
def toggle_user_active_api(request, user_id):
    """AJAX: admin toggles is_active on a user (cannot deactivate self)."""
    User = get_user_model()
    target = get_object_or_404(User, pk=user_id)
    if target.pk == request.user.pk:
        return JsonResponse({"error": "You cannot deactivate your own account."}, status=400)
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    return JsonResponse({"ok": True, "is_active": target.is_active})


@login_required
@require_POST
@csrf_protect
def bootstrap_admin_view(request):
    """First-run helper: if no admin exists yet, current user can claim it.

    Disappears as soon as ANY admin/staff/superuser is set up. Safe for a
    fresh install (your Wellnest dev account); refuses on any subsequent call.
    """
    if not _no_admins_exist():
        return redirect("accounts:profile")
    user = request.user
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])
    profile, _ = DoctorProfile.objects.get_or_create(user=user)
    profile.role = DoctorProfile.ROLE_ADMIN
    profile.save(update_fields=["role"])
    return redirect("accounts:profile")
