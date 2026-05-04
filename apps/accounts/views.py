from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import DoctorProfileForm, WellnestSignInForm, WellnestSignUpForm
from .models import DoctorProfile


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
        login(request, user)
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
    return render(request, "accounts/profile.html", {"form": form, "profile": profile})
