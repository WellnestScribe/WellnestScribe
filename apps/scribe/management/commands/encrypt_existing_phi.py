"""Encrypt all existing plaintext PHI rows in-place.

Run this once after setting FIELD_ENCRYPTION_KEY in the environment:

    python manage.py encrypt_existing_phi

The command reads every row through the ORM (which decrypts or passes through
plaintext for legacy rows) and immediately saves the affected fields back (which
encrypts them with the current key).  Rows that are already encrypted are
decrypted first then re-encrypted — safe to run multiple times.

Progress is printed to stdout; errors on individual rows are logged and skipped
so a single bad row does not abort the whole run.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from scribe.models import ScribeSession, SOAPNote

logger = logging.getLogger(__name__)

SESSION_FIELDS = [
    "title", "chief_complaint", "patient_name",
    "patient_identifier", "transcript", "raw_transcript",
]
NOTE_FIELDS = [
    "visit_summary", "subjective", "objective",
    "assessment", "plan", "narrative", "full_note", "edited_note",
]


class Command(BaseCommand):
    help = "Encrypt existing plaintext PHI fields using FIELD_ENCRYPTION_KEY"

    def handle(self, *args, **options):
        key = (getattr(settings, "FIELD_ENCRYPTION_KEY", None) or "").strip()
        if not key:
            self.stderr.write(self.style.ERROR(
                "FIELD_ENCRYPTION_KEY is not set — nothing to do.  "
                "Set it in .env or Azure App Service config and re-run."
            ))
            return

        # ── ScribeSession ─────────────────────────────────────────────────
        total = ScribeSession.objects.count()
        self.stdout.write(f"Encrypting {total} ScribeSession rows …")
        done = 0
        errors = 0
        for session in ScribeSession.objects.iterator(chunk_size=200):
            try:
                session.save(update_fields=SESSION_FIELDS)
                done += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.error("encrypt_existing_phi: session pk=%s error: %s", session.pk, exc)
        self.stdout.write(self.style.SUCCESS(f"  Sessions: {done} encrypted, {errors} errors"))

        # ── SOAPNote ──────────────────────────────────────────────────────
        total = SOAPNote.objects.count()
        self.stdout.write(f"Encrypting {total} SOAPNote rows …")
        done = 0
        errors = 0
        for note in SOAPNote.objects.iterator(chunk_size=200):
            try:
                note.save(update_fields=NOTE_FIELDS)
                done += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.error("encrypt_existing_phi: note pk=%s error: %s", note.pk, exc)
        self.stdout.write(self.style.SUCCESS(f"  Notes:    {done} encrypted, {errors} errors"))

        self.stdout.write(self.style.SUCCESS("Done."))
