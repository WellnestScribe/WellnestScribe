"""Demote a user back to clinician + remove staff/superuser flags.

Usage:
    python manage.py demote <username-or-email>
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import DoctorProfile


class Command(BaseCommand):
    help = "Demote a user to clinician and remove staff/superuser."

    def add_arguments(self, parser):
        parser.add_argument("identifier", help="Username or email address.")

    def handle(self, *args, **opts):
        UserModel = get_user_model()
        ident = opts["identifier"]
        try:
            if "@" in ident:
                user = UserModel.objects.get(email__iexact=ident)
            else:
                user = UserModel.objects.get(username=ident)
        except UserModel.DoesNotExist as exc:
            raise CommandError(f"No user matches {ident!r}.") from exc

        profile, _ = DoctorProfile.objects.get_or_create(user=user)
        profile.role = DoctorProfile.ROLE_CLINICIAN
        profile.save(update_fields=["role"])

        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])

        self.stdout.write(self.style.SUCCESS(f"{user.username} demoted to clinician."))
