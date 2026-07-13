"""Find (and optionally fix) coded diagnoses that the source note actually negates.

The deterministic diagnosis extractor was hardened on 2026-07-13 so a denied
condition ("denies diabetes") can no longer be auto-coded. That fix is
PREVENTIVE - it does not touch diagnoses already written to the database before
the fix. This command sweeps existing AI-suggested diagnoses and finds any whose
stored source sentence (Diagnosis.notes) is negated, family-history, or resolved.

    python manage.py flag_negated_diagnoses            # dry-run report only
    python manage.py flag_negated_diagnoses --apply     # downgrade unsigned ones

Safety rules:
  * Only AI-suggested diagnoses that are currently active/chronic are considered.
  * Signed encounters are a legal record - they are REPORTED but never modified
    (a clinician must amend those by hand).
  * With --apply, an offending diagnosis on an UNSIGNED encounter is moved to
    status "suspected" (so it drops off the active Problem List) and annotated,
    never deleted.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from emr.models import Diagnosis
from emr.services.scribe_import import DIAGNOSIS_MATCHERS, _condition_denied_in_text

_KEYWORDS_BY_CODE = {m["code"]: m["keywords"] for m in DIAGNOSIS_MATCHERS}
_FLAG_NOTE = "[AUTO-FLAGGED: source note negates or does not support this diagnosis - verify or remove]"


def _keyword_present(notes: str, keywords: list[str]) -> bool:
    """True if any keyword appears as a whole word in the source note. A False
    here on an AI diagnosis means it was a substring false-positive (e.g. 'uri'
    matched inside 'during')."""
    low = (notes or "").lower()
    return any(re.search(rf"\b{re.escape(kw.lower())}\b", low) for kw in keywords)


def _suspect_reason(notes: str, keywords: list[str]) -> str | None:
    if _condition_denied_in_text(notes, keywords):
        return "negated / family history / resolved in the source note"
    # 'Known condition on file (...)' rows legitimately won't contain the keyword.
    if notes.strip().lower().startswith("known condition on file"):
        return None
    if not _keyword_present(notes, keywords):
        return "phantom match - keyword not actually present in the source (substring false positive)"
    return None


class Command(BaseCommand):
    help = "Report/downgrade coded diagnoses whose source note negates them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually downgrade offending diagnoses on unsigned encounters (default: report only).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        qs = (
            Diagnosis.objects.filter(ai_suggested=True, status__in=["active", "chronic"])
            .select_related("encounter", "patient")
            .order_by("patient_id", "encounter__encounter_date")
        )

        flagged = 0
        changed = 0
        skipped_signed = 0

        for dx in qs:
            keywords = _KEYWORDS_BY_CODE.get(dx.icd10_code)
            if not keywords or not (dx.notes or "").strip():
                continue
            reason = _suspect_reason(dx.notes, keywords)
            if not reason:
                continue

            flagged += 1
            signed = getattr(dx.encounter, "encounter_status", "") == "signed"
            patient = dx.patient
            self.stdout.write(
                f"[{'SIGNED - manual' if signed else 'unsigned'}] "
                f"{patient} · {dx.icd10_code} {dx.icd10_description} "
                f"(enc {dx.encounter.encounter_date:%Y-%m-%d}) — {reason}\n"
                f"    source: \"{(dx.notes or '').strip()[:110]}\""
            )

            if signed:
                skipped_signed += 1
                continue

            if apply:
                dx.status = "suspected"
                if _FLAG_NOTE not in (dx.notes or ""):
                    dx.notes = f"{_FLAG_NOTE}\n{dx.notes or ''}".strip()
                dx.save(update_fields=["status", "notes", "updated_at"])
                changed += 1

        self.stdout.write("")
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"Flagged {flagged} suspect diagnosis(es); downgraded {changed} on unsigned "
                f"encounters to 'suspected'; left {skipped_signed} signed record(s) for manual amendment."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {flagged} suspect diagnosis(es) found "
                f"({skipped_signed} on signed encounters). Re-run with --apply to downgrade the unsigned ones."
            ))
