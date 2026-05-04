"""Delete audio files older than AUTO_DELETE_AUDIO_DAYS.

Run from cron or a Windows Scheduled Task in production:
    python manage.py purge_audio
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from scribe.models import ScribeSession


class Command(BaseCommand):
    help = "Delete audio files older than AUTO_DELETE_AUDIO_DAYS (compliance retention)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without doing it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=settings.AUTO_DELETE_AUDIO_DAYS)
        qs = ScribeSession.objects.exclude(audio_file="").filter(created_at__lt=cutoff)
        count = 0
        for session in qs:
            if not session.audio_file:
                continue
            if options["dry_run"]:
                self.stdout.write(f"DRY: would delete {session.audio_file.name}")
            else:
                session.audio_file.delete(save=False)
                session.save(update_fields=["audio_file"])
            count += 1
        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(self.style.SUCCESS(f"{verb} {count} audio file(s) older than {cutoff:%Y-%m-%d}"))
