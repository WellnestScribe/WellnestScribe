"""Local (WellnestScribe built-in) EMR backend.

Wraps the existing Django `emr` app models so they implement the same
EMRBackend interface as the GNU Health adapter. This backend is always
available — no external service required.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


class LocalEMRBackend:
    """Adapter over WellnestScribe's own Django EMR models."""

    # ── Connection ────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        try:
            from emr.models import Patient
            Patient.objects.count()
            return {"status": "connected", "backend": "local"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    # ── Patients ──────────────────────────────────────────────────────────────

    def search_patients(self, query: str, *, limit: int = 20) -> list[dict]:
        from emr.models import Patient
        from django.db.models import Q

        q = query.strip()
        if not q:
            return []
        qs = Patient.objects.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(hospital_number__icontains=q)
        ).order_by("last_name", "first_name")[:limit]
        return [_patient_to_dict(p) for p in qs]

    def get_patient(self, external_id: str) -> dict | None:
        from emr.models import Patient

        try:
            p = Patient.objects.get(pk=int(external_id))
            return _patient_to_dict(p)
        except Patient.DoesNotExist:
            return None

    def create_patient(self, data: dict) -> dict:
        from emr.models import Patient, Organisation

        org = _default_org()
        p = Patient.objects.create(
            organisation=org,
            first_name=data.get("first_name") or data.get("full_name", "").split()[0],
            last_name=data.get("last_name") or " ".join(data.get("full_name", "").split()[1:]),
            date_of_birth=data.get("dob"),
            sex=data.get("sex", "u"),
        )
        return _patient_to_dict(p)

    # ── Encounters ────────────────────────────────────────────────────────────

    def push_encounter(self, patient_external_id: str, encounter_data: dict) -> dict:
        from emr.models import Patient, Encounter, Organisation

        org = _default_org()
        try:
            patient = Patient.objects.get(pk=int(patient_external_id))
        except Patient.DoesNotExist:
            raise ValueError(f"Patient {patient_external_id} not found in local EMR.")

        enc = Encounter.objects.create(
            organisation=org,
            patient=patient,
            encounter_date=encounter_data.get("encounter_date") or date.today(),
            chief_complaint=(encounter_data.get("chief_complaint") or "")[:500],
            history_of_presenting_illness=encounter_data.get("subjective") or encounter_data.get("clinical_summary") or "",
            physical_examination=encounter_data.get("objective") or "",
            assessment_notes=encounter_data.get("assessment") or "",
            plan_notes=encounter_data.get("plan") or "",
        )
        return {
            "id": str(enc.pk),
            "patient_id": patient_external_id,
            "encounter_date": str(enc.encounter_date),
            "_backend": "local",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _patient_to_dict(p) -> dict:
    return {
        "id": str(p.pk),
        "name": p.full_name,
        "dob": str(p.date_of_birth or ""),
        "sex": p.sex,
        "ref": getattr(p, "hospital_number", "") or "",
        "_backend": "local",
    }


def _default_org():
    """Return the first Organisation or raise if none exist."""
    from emr.models import Organisation

    org = Organisation.objects.first()
    if org is None:
        raise RuntimeError(
            "No Organisation found in local EMR. "
            "Create one at /emr/settings/ before using the local backend."
        )
    return org
