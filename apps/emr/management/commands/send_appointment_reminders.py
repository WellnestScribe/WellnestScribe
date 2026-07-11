"""Email appointment reminders to patients with an upcoming visit.

Run daily (e.g. Windows Task Scheduler / cron):
    python manage.py send_appointment_reminders            # patients due tomorrow
    python manage.py send_appointment_reminders --when today
    python manage.py send_appointment_reminders --dry-run  # print, don't send

Uses the SMTP configured via EMAIL_* env vars. Until those are set, Django's
console backend prints the messages to the server log, so this runs safely now.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from emr.models import Appointment


class Command(BaseCommand):
    help = "Email appointment reminders to patients due tomorrow (run daily)."

    def add_arguments(self, parser):
        parser.add_argument("--when", choices=["tomorrow", "today"], default="tomorrow")
        parser.add_argument("--dry-run", action="store_true", help="Print, do not send.")

    def handle(self, *args, **opts):
        offset = timedelta(days=1) if opts["when"] == "tomorrow" else timedelta(0)
        target = timezone.localdate() + offset
        start = timezone.make_aware(datetime.combine(target, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(target, datetime.max.time()))

        appts = (
            Appointment.objects.filter(
                scheduled_for__range=(start, end),
                status__in=["scheduled", "checked_in"],
            )
            .select_related("patient", "organisation")
            .order_by("scheduled_for")
        )

        sent = skipped = failed = 0
        for a in appts:
            email = (a.patient.email or "").strip()
            if not email:
                skipped += 1
                continue
            when_str = timezone.localtime(a.scheduled_for).strftime("%A, %B %d at %I:%M %p")
            clinic = a.organisation.name
            subject = f"Appointment reminder - {clinic}"
            body = (
                f"Hello {a.patient.display_name},\n\n"
                f"This is a friendly reminder of your appointment at {clinic} on {when_str}.\n\n"
                f"If you need to reschedule, please contact the clinic.\n\n"
                f"- {clinic}"
            )
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] {email} -> {when_str}")
                continue
            try:
                send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stderr.write(f"Failed {email}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"Reminders for {target}: {sent} sent, {skipped} skipped (no email), {failed} failed."
        ))
