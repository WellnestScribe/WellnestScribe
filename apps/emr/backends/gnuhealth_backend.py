"""GNU Health backend via Tryton 7.0 XML-RPC.

Tryton exposes an XML-RPC server at http://host:port/.
Authentication: common.login(db, user, password) → (uid, session_id)
Model calls:    object.execute(db, uid, session, model, method, [args], {kwargs})

GNU Health patient model: 'gnuhealth.patient'
Underlying party model:   'party.party'
Evaluation model:         'gnuhealth.patient.evaluation'
"""

from __future__ import annotations

import logging
import threading
import xmlrpc.client
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


class GnuHealthBackend:
    """Thread-safe GNU Health client using Tryton XML-RPC."""

    def __init__(self, host: str, port: int, db: str, user: str, password: str):
        self._db = db
        self._user = user
        self._password = password
        base_url = f"http://{host}:{port}"
        self._common = xmlrpc.client.ServerProxy(f"{base_url}/")
        self._rpc = xmlrpc.client.ServerProxy(f"{base_url}/{db}/")
        self._lock = threading.Lock()
        self._uid: int | None = None
        self._session: str | None = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _auth(self) -> tuple[int, str]:
        """Return (uid, session), logging in if needed. Thread-safe."""
        with self._lock:
            if self._uid is None:
                result = self._common.common.login(self._db, self._user, self._password)
                if not result:
                    raise ConnectionError(
                        f"GNU Health login failed for user={self._user!r} db={self._db!r}"
                    )
                self._uid, self._session = result[0], result[1]
        return self._uid, self._session  # type: ignore[return-value]

    def _invalidate_session(self) -> None:
        with self._lock:
            self._uid = None
            self._session = None

    def _execute(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None) -> Any:
        """Execute a Tryton model method, auto-retrying once on session expiry."""
        uid, session = self._auth()
        try:
            return self._rpc.object.execute(
                self._db, uid, session, model, method,
                args or [], kwargs or {},
            )
        except xmlrpc.client.Fault as exc:
            if "session" in str(exc).lower():
                self._invalidate_session()
                uid, session = self._auth()
                return self._rpc.object.execute(
                    self._db, uid, session, model, method,
                    args or [], kwargs or {},
                )
            raise

    # ── Public API ────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        try:
            version = self._common.common.version()
            uid, _ = self._auth()
            return {"status": "connected", "version": version, "uid": uid}
        except Exception as exc:
            logger.warning("GNU Health health_check failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def search_patients(self, query: str, *, limit: int = 20) -> list[dict]:
        """Search party.party by name, then filter to those with gnuhealth.patient."""
        q = query.strip()
        if not q:
            return []
        try:
            # Search parties (persons) whose name contains the query
            party_domain = [
                ["OR",
                 ["name", "ilike", f"%{q}%"],
                 ["rec_name", "ilike", f"%{q}%"]],
                ["is_person", "=", True],
            ]
            party_ids = self._execute("party.party", "search", [party_domain, 0, limit])
            if not party_ids:
                return []

            # Find gnuhealth.patient records for those parties
            patient_domain = [["name", "in", party_ids]]
            patient_ids = self._execute("gnuhealth.patient", "search", [patient_domain])
            if not patient_ids:
                return []

            # Read patient + party fields
            patients_raw = self._execute(
                "gnuhealth.patient", "read",
                [patient_ids, ["name", "sex", "dob", "id", "rec_name"]],
            )
            parties_raw = self._execute(
                "party.party", "read",
                [party_ids, ["id", "name", "ref"]],
            )
            party_map = {p["id"]: p for p in (parties_raw or [])}

            results = []
            for pat in (patients_raw or []):
                party = party_map.get(pat.get("name"))
                results.append({
                    "id": str(pat["id"]),
                    "name": pat.get("rec_name") or (party or {}).get("name", ""),
                    "dob": str(pat.get("dob") or ""),
                    "sex": pat.get("sex", "u"),
                    "ref": (party or {}).get("ref", ""),
                    "_backend": "gnuhealth",
                })
            return results
        except Exception as exc:
            logger.error("GnuHealthBackend.search_patients error: %s", exc)
            return []

    def get_patient(self, external_id: str) -> dict | None:
        try:
            pid = int(external_id)
            rows = self._execute(
                "gnuhealth.patient", "read",
                [[pid], ["name", "sex", "dob", "id", "rec_name"]],
            )
            if not rows:
                return None
            pat = rows[0]
            return {
                "id": str(pat["id"]),
                "name": pat.get("rec_name", ""),
                "dob": str(pat.get("dob") or ""),
                "sex": pat.get("sex", "u"),
                "_backend": "gnuhealth",
            }
        except Exception as exc:
            logger.error("GnuHealthBackend.get_patient(%s) error: %s", external_id, exc)
            return None

    def create_patient(self, data: dict) -> dict:
        """
        Create a party.party (person) and link a gnuhealth.patient record.
        Returns the created patient dict with id set.
        """
        full_name = data.get("full_name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        if not full_name:
            raise ValueError("create_patient requires at least full_name or first_name+last_name")

        # Create party
        party_vals = {
            "name": full_name,
            "is_person": True,
        }
        if ref := data.get("ref"):
            party_vals["ref"] = ref
        party_id = self._execute("party.party", "create", [[party_vals]])[0]

        # Create gnuhealth.patient
        patient_vals: dict = {"name": party_id}
        if dob := data.get("dob"):
            patient_vals["dob"] = str(dob)
        if sex := data.get("sex"):
            patient_vals["sex"] = sex
        patient_id = self._execute("gnuhealth.patient", "create", [[patient_vals]])[0]

        return {
            "id": str(patient_id),
            "name": full_name,
            "dob": str(data.get("dob") or ""),
            "sex": data.get("sex", "u"),
            "_backend": "gnuhealth",
        }

    def push_encounter(self, patient_external_id: str, encounter_data: dict) -> dict:
        """
        Create a gnuhealth.patient.evaluation for the given patient.
        Returns the created evaluation dict with id set.
        """
        pid = int(patient_external_id)
        encounter_date = encounter_data.get("encounter_date") or str(date.today())

        eval_vals: dict = {
            "patient": pid,
            "evaluation_date": encounter_date,
            "chief_complaint": (encounter_data.get("chief_complaint") or "")[:255],
            "present_illness": encounter_data.get("clinical_summary") or "",
            "evaluation_type": "o",  # outpatient
        }

        # Subjective / Objective / Assessment / Plan mapped to GNU Health fields
        if notes := encounter_data.get("subjective"):
            eval_vals["present_illness"] = notes
        if plan := encounter_data.get("plan"):
            eval_vals["treatment"] = plan
        if assessment := encounter_data.get("assessment"):
            eval_vals["diagnosis"] = assessment[:255]

        eval_id = self._execute("gnuhealth.patient.evaluation", "create", [[eval_vals]])[0]
        logger.info("Pushed encounter to GNU Health: evaluation_id=%s patient=%s", eval_id, pid)
        return {
            "id": str(eval_id),
            "patient_id": patient_external_id,
            "encounter_date": encounter_date,
            "_backend": "gnuhealth",
        }
