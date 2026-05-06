from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .forms import DoctorProfileForm, WellnestSignInForm, WellnestSignUpForm
from .models import DoctorProfile


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
        login(request, form.get_user())
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
