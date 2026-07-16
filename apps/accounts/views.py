import json

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .forms import DoctorProfileForm, WellnestSignInForm, WellnestSignUpForm
from .models import DoctorProfile, PlatformControl


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
        org = form.cleaned_data.get("organisation")
        DoctorProfile.objects.create(
            user=user,
            full_name=form.cleaned_data["full_name"],
            role=form.cleaned_data["role"],
            specialty=form.cleaned_data["specialty"],
            facility=org.name if org else "",
        )
        if org is not None:
            from emr.models import OrganisationMembership
            _membership_role = {
                DoctorProfile.ROLE_ADMIN: "admin",
                DoctorProfile.ROLE_NURSE: "nurse",
                DoctorProfile.ROLE_ED_NURSE: "nurse",
                DoctorProfile.ROLE_RECEPTIONIST: "receptionist",
            }.get(form.cleaned_data["role"], "doctor")
            OrganisationMembership.objects.get_or_create(
                user=user,
                organisation=org,
                defaults={"role": _membership_role, "is_default": True},
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


def password_help_view(request):
    """Password-reset guidance. Accounts are admin-provisioned and there is no
    public email flow, so the honest reset path is: ask your clinic administrator
    (they reset it from Users → Set password). Its own neat page so the sign-in
    'Forgot password?' link goes somewhere real."""
    return render(request, "accounts/password_help.html")


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
    is_admin = bool(profile.is_admin)
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "profile": profile,
            "bootstrap_admin_available": _no_admins_exist(),
            "is_admin": is_admin,
            "platform_control": PlatformControl.get() if is_admin else None,
            "demo_mode_choices": PlatformControl.MODE_CHOICES,
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


@_require_admin
@require_POST
@csrf_protect
def demo_control_api(request):
    """Admin-only: set the platform-wide demo mode (off / limited / locked).

    Powers the 'Demo mode' card on the profile page so an admin can lock the
    platform down from the UI during a public pitch - no redeploy needed.
    """
    try:
        body = json.loads(request.body)
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)

    mode = (body.get("demo_mode") or "").strip()
    valid_modes = {m[0] for m in PlatformControl.MODE_CHOICES}
    if mode not in valid_modes:
        return JsonResponse({"error": "invalid mode"}, status=400)

    try:
        note_limit = max(1, min(50, int(body.get("note_limit", 1))))
    except (TypeError, ValueError):
        note_limit = 1
    message = (body.get("message") or "").strip()[:300]

    control = PlatformControl.get()
    control.demo_mode = mode
    control.note_limit = note_limit
    control.message = message
    control.updated_by = request.user
    control.save()
    return JsonResponse({
        "ok": True,
        "demo_mode": control.demo_mode,
        "note_limit": control.note_limit,
        "message": control.message,
        "effective_message": control.message_for_mode(),
    })


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
        "membership_role_choices": OrganisationMembership._meta.get_field("role").choices,
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
def create_organisation_api(request):
    """Admin: add a facility (organisation) so it appears in the signup dropdown."""
    from emr.models import Organisation
    try:
        body = json.loads(request.body)
        name = (body.get("name") or "").strip()
        parish = (body.get("parish") or "").strip()
        org_type = (body.get("organisation_type") or "private_clinic").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    if not name:
        return JsonResponse({"error": "Facility name is required."}, status=400)
    if Organisation.objects.filter(name__iexact=name).exists():
        return JsonResponse({"error": f"A facility named '{name}' already exists."}, status=400)
    org = Organisation.objects.create(name=name, parish=parish, organisation_type=org_type)
    return JsonResponse({"ok": True, "id": org.pk, "name": org.name})


@_require_admin
@require_POST
@csrf_protect
def organisation_deactivate_api(request, org_id):
    """Soft-delete: move a facility to the recycle bin (hidden, data kept)."""
    from emr.models import Organisation
    org = get_object_or_404(Organisation, pk=org_id)
    org.is_active = False
    org.save(update_fields=["is_active"])
    return JsonResponse({"ok": True})


@_require_admin
@require_POST
@csrf_protect
def organisation_restore_api(request, org_id):
    """Restore a facility from the recycle bin."""
    from emr.models import Organisation
    org = get_object_or_404(Organisation, pk=org_id)
    org.is_active = True
    org.save(update_fields=["is_active"])
    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def organisation_delete_api(request, org_id):
    """Permanently delete a facility. Superuser only, must be in the recycle bin
    (deactivated) first, and must confirm by typing the exact name."""
    if not (request.user.is_authenticated and request.user.is_superuser):
        return JsonResponse({"error": "Only a superuser can permanently delete a facility."}, status=403)
    from emr.models import Organisation
    org = get_object_or_404(Organisation, pk=org_id)
    if org.is_active:
        return JsonResponse({"error": "Deactivate the facility first (recycle bin), then delete."}, status=400)
    try:
        body = json.loads(request.body)
        confirm = (body.get("confirm_name") or "").strip()
    except (ValueError, AttributeError):
        return JsonResponse({"error": "bad request"}, status=400)
    if confirm != org.name:
        return JsonResponse({"error": "Type the exact facility name to confirm deletion."}, status=400)
    name = org.name
    org.delete()
    return JsonResponse({"ok": True, "name": name})


def _org_export_data(org):
    """Full portable data dict for a facility (patients + clinical records)."""
    from django.utils import timezone as _tz
    data = {
        "exported_at": _tz.now().isoformat(),
        "organisation": {"id": org.pk, "name": org.name, "parish": org.parish, "type": org.organisation_type},
        "patients": [],
    }
    for p in org.patients.all().prefetch_related("encounters", "diagnoses", "medications", "vitals", "allergies"):
        data["patients"].append({
            "mrn": p.mrn,
            "first_name": p.legal_first_name,
            "last_name": p.legal_last_name,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "sex": p.sex,
            "trn": p.trn, "nhf_card_number": p.nhf_card_number,
            "phone": p.phone_primary, "parish": p.parish, "community": p.community,
            "allergies": [{"allergen": a.allergen_name, "severity": a.severity} for a in p.allergies.all()],
            "encounters": [{
                "date": e.encounter_date.isoformat() if e.encounter_date else None,
                "type": e.encounter_type, "status": e.encounter_status,
                "chief_complaint": e.chief_complaint,
                "assessment": e.assessment_notes, "plan": e.plan_notes,
            } for e in p.encounters.all()],
            "diagnoses": [{"icd10": d.icd10_code, "description": d.icd10_description, "status": d.status} for d in p.diagnoses.all()],
            "medications": [{"drug": m.drug_name_generic, "dose": str(m.dose_amount or ""), "unit": m.dose_unit, "frequency": m.frequency} for m in p.medications.all()],
            "vitals": [{
                "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None,
                "bp": f"{v.bp_systolic}/{v.bp_diastolic}" if v.bp_systolic and v.bp_diastolic else None,
                "weight_kg": str(v.weight_kg or ""), "glucose_mmol": str(v.blood_glucose_mmol or ""),
            } for v in p.vitals.all()],
        })
    return data


def _org_export_csv_response(org, filename=None):
    """One-row-per-patient CSV (demographics + counts + active problems/meds)."""
    import csv
    from django.http import HttpResponse
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename or ("wellnest-" + str(org.pk) + "-patients")}.csv"'
    writer = csv.writer(resp)
    writer.writerow([
        "MRN", "First name", "Last name", "Date of birth", "Sex", "TRN", "NHF",
        "Phone", "Parish", "Community", "Encounters", "Active diagnoses", "Current medications",
    ])
    for p in org.patients.all().prefetch_related("encounters", "diagnoses", "medications"):
        active_dx = "; ".join(d.icd10_code for d in p.diagnoses.all() if d.status == "active")
        active_meds = "; ".join(m.drug_name_generic for m in p.medications.all() if m.status == "active")
        writer.writerow([
            p.mrn, p.legal_first_name, p.legal_last_name,
            p.date_of_birth or "", p.sex, p.trn, p.nhf_card_number,
            p.phone_primary, p.parish, p.community, p.encounters.count(), active_dx, active_meds,
        ])
    return resp


@login_required
def organisation_export_api(request, org_id):
    """Export a facility's data for portability. ?format=csv for CSV, else JSON."""
    from django.http import HttpResponseForbidden
    from emr.models import Organisation
    profile = getattr(request.user, "doctor_profile", None)
    if not (profile and profile.is_admin):
        return HttpResponseForbidden("Admin access required.")
    org = get_object_or_404(Organisation, pk=org_id)
    if request.GET.get("format") == "csv":
        return _org_export_csv_response(org)
    resp = JsonResponse(_org_export_data(org), json_dumps_params={"indent": 2})
    resp["Content-Disposition"] = f'attachment; filename="wellnest-{org.pk}-export.json"'
    return resp


@login_required
def subscription_view(request):
    """Self-service page for a user: view their facility's plan + status,
    see the pricing tiers (current one highlighted), and export their data."""
    from emr.services.access import get_membership
    ctx = get_membership(request.user)
    org = ctx.organisation

    # Pricing tiers (from docs/July_2026_Financials_Estimate.md). `code` matches
    # Organisation.subscription_tier where one exists, so the active plan lights up.
    plans = [
        {
            "code": "scribe", "name": "Standard", "usd": "94", "jmd": "15,000", "cadence": "/month",
            "popular": False, "best_for": "~15-20 patients / day",
            "features": ["500 notes / month", "SOAP, narrative & chart", "QR to any EHR, no integration",
                         "Front-desk queue & appointments", "AI edits included per note"],
        },
        {
            "code": "practice", "name": "Standard + EMR", "usd": "144", "jmd": "23,000", "cadence": "/month",
            "popular": False, "best_for": "Scribe + full records",
            "features": ["Everything in Standard", "The lightweight EMR", "Charts, records & problem list",
                         "Patient timeline & documents"],
        },
        {
            "code": "professional", "name": "Professional", "usd": "190", "jmd": "30,000", "cadence": "/month",
            "popular": True, "best_for": "~25-40 patients / day",
            "features": ["1,100 notes / month", "Everything in Standard", "Recordings up to 5 hours",
                         "Priority support"],
        },
        {
            "code": "professional_emr", "name": "Professional + EMR", "usd": "240", "jmd": "38,000", "cadence": "/month",
            "popular": False, "best_for": "Full stack, high volume",
            "features": ["Everything in Professional", "The lightweight EMR", "Patient timeline & documents",
                         "Best-value bundle"],
        },
    ]
    for p in plans:
        p["current"] = (org.subscription_tier == p["code"])

    return render(request, "accounts/subscription.html", {
        "org": org,
        "membership": ctx.membership,
        "plans": plans,
    })


@login_required
def my_data_export(request):
    """Export the signed-in user's own facility data (JSON or ?format=csv)."""
    from emr.services.access import get_membership
    org = get_membership(request.user).organisation
    if request.GET.get("format") == "csv":
        return _org_export_csv_response(org, filename="wellnest-my-patients")
    resp = JsonResponse(_org_export_data(org), json_dumps_params={"indent": 2})
    resp["Content-Disposition"] = 'attachment; filename="wellnest-my-data.json"'
    return resp


def _doc_title(path):
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
            if s:
                break
    except Exception:  # noqa: BLE001
        pass
    return path.stem.replace("_", " ").replace("-", " ").title()


@login_required
def docs_view(request, slug=None):
    """Render the project's docs/*.md policy + reference files as an in-app page."""
    from django.conf import settings as dj_settings
    from django.http import HttpResponseForbidden

    profile = getattr(request.user, "doctor_profile", None)
    if not (profile and profile.is_admin):
        return HttpResponseForbidden("Admin access required.")

    docs_dir = dj_settings.BASE_DIR / "docs"
    files = sorted(docs_dir.glob("*.md"), key=lambda p: p.name) if docs_dir.exists() else []
    entries = [{"slug": p.stem, "title": _doc_title(p), "name": p.name} for p in files]

    current = next((e for e in entries if e["slug"] == slug), None) or (entries[0] if entries else None)
    content_html = ""
    if current:
        try:
            import markdown as _md
            raw = (docs_dir / current["name"]).read_text(encoding="utf-8")
            content_html = _md.markdown(
                raw, extensions=["tables", "fenced_code", "sane_lists", "toc"]
            )
        except Exception:  # noqa: BLE001
            content_html = "<p class='text-danger'>Could not render this document.</p>"

    return render(request, "accounts/docs.html", {
        "entries": entries,
        "current": current,
        "content_html": content_html,
    })


@login_required
@require_http_methods(["GET", "POST"])
def billing_view(request):
    """Manual subscription / billing management (no processor yet).

    Admins set each facility's tier, status, seats, paid-through date and notes.
    Suspending a facility turns OFF the AI scribe only - EMR record access is
    never gated on billing (patient safety).
    """
    profile = getattr(request.user, "doctor_profile", None)
    if not (profile and profile.is_admin):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Admin access required.")

    from datetime import datetime

    from emr.constants import SUBSCRIPTION_STATUS_CHOICES, SUBSCRIPTION_TIER_CHOICES
    from emr.models import Organisation

    if request.method == "POST":
        org = get_object_or_404(Organisation, pk=request.POST.get("org_id"))
        tier = request.POST.get("subscription_tier", "")
        status = request.POST.get("subscription_status", "")
        if tier in {c[0] for c in SUBSCRIPTION_TIER_CHOICES}:
            # Decided policy: block a downgrade that would REMOVE the EMR from a
            # clinic that already has patient records - that strips access to
            # medical records (safety + record-keeping). Upgrades stay seamless.
            if org.has_emr and tier not in Organisation.EMR_TIERS:
                from emr.models import Patient
                if Patient.objects.filter(organisation=org).exists():
                    messages.error(
                        request,
                        f"{org.name} can't be downgraded off the EMR - it has patient "
                        f"records, and removing EMR would cut access to them. Keep an EMR "
                        f"plan, or contact WellNest to export and offboard.",
                    )
                    return redirect("accounts:billing")
            org.subscription_tier = tier
        if status in {c[0] for c in SUBSCRIPTION_STATUS_CHOICES}:
            org.subscription_status = status
        try:
            org.provider_seats = max(0, int(request.POST.get("provider_seats") or org.provider_seats))
        except (TypeError, ValueError):
            pass
        exp = (request.POST.get("subscription_expires") or "").strip()
        if exp:
            try:
                org.subscription_expires = datetime.strptime(exp, "%Y-%m-%d").date()
            except ValueError:
                pass
        else:
            org.subscription_expires = None
        amt = (request.POST.get("monthly_amount") or "").strip()
        org.monthly_amount = amt or None
        org.billing_notes = (request.POST.get("billing_notes") or "")[:2000]
        org.save()
        log_audit_event_safe(request, org, f"Billing updated: {org.subscription_tier}/{org.subscription_status}")
        messages.success(request, f"Billing updated for {org.name}.")
        return redirect("accounts:billing")

    return render(request, "accounts/billing.html", {
        "organisations": Organisation.objects.all().order_by("name"),
        "tier_choices": SUBSCRIPTION_TIER_CHOICES,
        "status_choices": SUBSCRIPTION_STATUS_CHOICES,
    })


def log_audit_event_safe(request, org, detail):
    try:
        from emr.services.audit import log_audit_event
        log_audit_event(request, org, action="update", resource_type="billing", resource_id=org.pk, detail=detail)
    except Exception:  # noqa: BLE001
        pass


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


@login_required
def security_events_view(request):
    """Intrusion-detection dashboard (admin only).

    Surfaces the SecurityEvents recorded by the audit middleware and the failed
    login signal: summary counts, top offending IPs, and a filterable event log.
    Read-only — a review surface, not a control panel.
    """
    from datetime import timedelta
    from django.db.models import Count
    from .models import SecurityEvent, user_is_admin

    if not user_is_admin(request.user):
        return redirect("scribe:record")

    # Filters
    try:
        days = int(request.GET.get("days", "7"))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    etype = request.GET.get("type", "").strip()
    severity = request.GET.get("severity", "").strip()

    since = timezone.now() - timedelta(days=days)
    qs = SecurityEvent.objects.filter(created_at__gte=since).select_related("user")
    if etype:
        qs = qs.filter(event_type=etype)
    if severity:
        qs = qs.filter(severity=severity)

    events = list(qs[:300])

    # Summary over the same window (unfiltered by type/severity so the cards
    # always show the full picture).
    window = SecurityEvent.objects.filter(created_at__gte=since)
    last_24h = SecurityEvent.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=24)
    ).count()
    by_type = {
        row["event_type"]: row["n"]
        for row in window.values("event_type").annotate(n=Count("id"))
    }
    by_severity = {
        row["severity"]: row["n"]
        for row in window.values("severity").annotate(n=Count("id"))
    }
    type_counts = [(label, by_type.get(val, 0)) for val, label in SecurityEvent.TYPE_CHOICES]
    top_ips = list(
        window.exclude(ip__isnull=True)
        .values("ip")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )

    return render(
        request,
        "accounts/security_events.html",
        {
            "events": events,
            "days": days,
            "type_filter": etype,
            "severity_filter": severity,
            "type_choices": SecurityEvent.TYPE_CHOICES,
            "severity_choices": SecurityEvent.SEVERITY_CHOICES,
            "total_window": window.count(),
            "last_24h": last_24h,
            "by_type": by_type,
            "by_severity": by_severity,
            "type_counts": type_counts,
            "top_ips": top_ips,
        },
    )
