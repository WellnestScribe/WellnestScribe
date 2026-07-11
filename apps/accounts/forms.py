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
    role = forms.ChoiceField(
        choices=DoctorProfile.ROLE_CHOICES,
        initial=DoctorProfile.ROLE_CLINICIAN,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    specialty = forms.ChoiceField(
        choices=DoctorProfile.SPECIALTY_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    organisation = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label="Default (assign later)",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Facility",
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
        # Lazy import avoids app-loading order issues; facilities are managed by admins.
        from emr.models import Organisation
        self.fields["organisation"].queryset = Organisation.objects.filter(
            is_active=True
        ).order_by("name")
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
            "suggestive_assist",
            "font_scale",
            "theme",
            "custom_instructions",
            "custom_terms",
        )
        # `role` is excluded - only admins / superusers can change roles, and
        # they do so via /admin/ or the manage.py promote command.
        widgets = {
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "specialty": forms.Select(attrs={"class": "form-select"}),
            "facility": forms.TextInput(attrs={"class": "form-control"}),
            "default_note_style": forms.Select(attrs={"class": "form-select"}),
            "suggestive_assist": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "font_scale": forms.NumberInput(
                attrs={"class": "form-control", "min": 80, "max": 160, "step": 10}
            ),
            "theme": forms.Select(attrs={"class": "form-select"}),
            "custom_instructions": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
            "custom_terms": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "HTN = hypertension\nDM = diabetes mellitus\nJDM = Jamaican diabetes management protocol\nOne abbreviation per line.",
                }
            ),
        }
