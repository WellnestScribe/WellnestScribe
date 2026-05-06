from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import DoctorProfile

User = get_user_model()


class WellnestSignInForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Username or email"}
        )
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Password"}
        )
    )


class WellnestSignUpForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Dr. Jane Smith"}
        ),
    )
    specialty = forms.ChoiceField(
        choices=DoctorProfile.SPECIALTY_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    facility = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Health centre / hospital"}
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("username", "email", "password1", "password2"):
            if name in self.fields:
                self.fields[name].widget.attrs.setdefault("class", "form-control")


class DoctorProfileForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = (
            "full_name",
            "title",
            "specialty",
            "facility",
            "default_note_style",
            "long_form_default",
            "font_scale",
            "theme",
            "custom_instructions",
        )
        # `role` is excluded — only admins / superusers can change roles, and
        # they do so via /admin/ or the manage.py promote command.
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "specialty": forms.Select(attrs={"class": "form-select"}),
            "facility": forms.TextInput(attrs={"class": "form-control"}),
            "default_note_style": forms.Select(attrs={"class": "form-select"}),
            "font_scale": forms.NumberInput(
                attrs={"class": "form-control", "min": 80, "max": 160, "step": 10}
            ),
            "theme": forms.Select(attrs={"class": "form-select"}),
            "custom_instructions": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
        }
