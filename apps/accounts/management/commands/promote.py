"""Promote a doctor to a higher role.

Usage:
    python manage.py promote <username-or-email>            # default: admin
    python manage.py promote <username-or-email> --role lead
    python manage.py promote <username-or-email> --role admin --staff

The --staff flag also flips Django's `is_staff` so the user can sign in to /admin/.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import DoctorProfile


class Command(BaseCommand):
    help = "Promote a user to clinician/lead/admin and optionally grant Django staff."

    def add_arguments(self, parser):
        parser.add_argument("identifier", help="Username or email address.")
        parser.add_argument(
            "--role",
            choices=[r[0] for r in DoctorProfile.ROLE_CHOICES],
            default="admin",
            help="Role to assign (default: admin).",
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            help="Also grant is_staff=True (lets the user sign in to /admin/).",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Also grant is_superuser=True (full Django admin power).",
        )

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
        old_role = profile.role
        profile.role = opts["role"]
        profile.save(update_fields=["role"])

        if opts["staff"]:
            user.is_staff = True
        if opts["superuser"]:
            user.is_staff = True
            user.is_superuser = True
        if opts["staff"] or opts["superuser"]:
            user.save(update_fields=["is_staff", "is_superuser"])

        self.stdout.write(self.style.SUCCESS(
            f"{user.username}: role {old_role} -> {profile.role}"
            + (" + staff" if opts["staff"] else "")
            + (" + superuser" if opts["superuser"] else "")
        ))
