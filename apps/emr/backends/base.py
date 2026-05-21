"""Abstract EMR backend interface.

Every backend (local Django EMR, GNU Health, future systems) implements these
methods so the rest of the codebase is backend-agnostic.

Data shapes are plain dicts so no ORM models leak across the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class PatientRecord(dict):
    """Typed alias — a dict with at least {id, name, dob, sex}."""


class EncounterRecord(dict):
    """Typed alias — a dict with at least {id, chief_complaint, date}."""


@runtime_checkable
class EMRBackend(Protocol):
    """Common interface all EMR backends must satisfy."""

    # ── Connection ────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Return {"status": "connected"|"error", ...}."""
        ...

    # ── Patients ──────────────────────────────────────────────────────────────

    def search_patients(self, query: str, *, limit: int = 20) -> list[PatientRecord]:
        """Full-text search across name / DOB / identifier."""
        ...

    def get_patient(self, external_id: str) -> PatientRecord | None:
        """Fetch one patient by the backend's native ID. None if not found."""
        ...

    def create_patient(self, data: dict) -> PatientRecord:
        """
        Create a patient in the backend.

        Minimum required keys in *data*:
          first_name, last_name  (or full_name)
          dob                    ISO-8601 date string
          sex                    "m" | "f" | "u"
        Returns the created patient record with the backend's native id.
        """
        ...

    # ── Encounters ────────────────────────────────────────────────────────────

    def push_encounter(
        self,
        patient_external_id: str,
        encounter_data: dict,
    ) -> EncounterRecord:
        """
        Push a clinical encounter to the backend.

        Minimum keys in *encounter_data*:
          chief_complaint
          clinical_summary    (free text — the AI note)
          encounter_date      ISO-8601 date string
        Returns the created encounter record with the backend's native id.
        """
        ...
