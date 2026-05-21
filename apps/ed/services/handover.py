"""AI-assisted shift handover SBAR generation.

Generates a Situation-Background-Assessment-Recommendation note
for each active patient at shift change. The charge nurse can
edit each note before signing off.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HANDOVER_SYSTEM_PROMPT = """\
You are a clinical handover assistant for an Emergency Department.
Generate a concise SBAR (Situation-Background-Assessment-Recommendation)
handover note for an incoming nurse or doctor.

Guidelines:
- Situation: 1 sentence — who is the patient and why are they here
- Background: 2-3 sentences — relevant medical history, triage findings, vitals
- Assessment: 1-2 sentences — current clinical status and any pending results
- Recommendation: 1-2 sentences — what the incoming team must do or watch for

Keep each section brief and clinically focused. Caribbean context: common
presentations include hypertensive emergencies, DKA, sickle cell crisis,
dengue, trauma, and acute asthma.

Respond ONLY with valid JSON:
{
  "situation": "...",
  "background": "...",
  "assessment": "...",
  "recommendation": "..."
}
"""


@dataclass
class SBARNote:
    situation: str = ""
    background: str = ""
    assessment: str = ""
    recommendation: str = ""
    error: str = ""


def generate_sbar(visit) -> SBARNote:
    """Generate an SBAR note for a single EDVisit. Never raises."""
    try:
        from scribe.services.clients import get_chat_client
        client = get_chat_client()
    except Exception as exc:
        logger.warning("AI client unavailable for SBAR: %s", exc)
        return SBARNote(error=str(exc))

    lines = [f"Patient: {visit.display_name}"]
    lines.append(f"Visit: {visit.visit_number}")
    lines.append(f"Arrival mode: {visit.get_arrival_mode_display()}")
    lines.append(f"Status: {visit.get_current_status_display()}")
    lines.append(f"Zone: {visit.get_current_zone_display()} {visit.current_bed}")
    lines.append(f"Time in department: {visit.time_in_department_minutes} minutes")

    try:
        t = visit.triage
        lines.append(f"Chief complaint: {t.chief_complaint}")
        lines.append(f"ESI: {t.esi_score}")
        lines.append(f"Mechanism: {t.get_mechanism_display()}")
        vitals = []
        if t.temp_celsius:
            vitals.append(f"Temp {t.temp_celsius}°C")
        if t.bp_systolic and t.bp_diastolic:
            vitals.append(f"BP {t.bp_systolic}/{t.bp_diastolic}")
        if t.pulse_bpm:
            vitals.append(f"HR {t.pulse_bpm}")
        if t.rr_rpm:
            vitals.append(f"RR {t.rr_rpm}")
        if t.spo2_percent:
            vitals.append(f"SpO₂ {t.spo2_percent}%")
        if t.pain_score is not None:
            vitals.append(f"Pain {t.pain_score}/10")
        if vitals:
            lines.append("Vitals: " + ", ".join(vitals))
        if t.gcs_total:
            lines.append(f"GCS: {t.gcs_total}/15")
        if t.pmh_list:
            lines.append("PMH: " + ", ".join(t.pmh_list))
        if t.allergies and not t.allergy_nkda:
            lines.append(f"Allergies: {t.allergies}")
        if t.current_medications:
            lines.append(f"Current meds: {t.current_medications}")
        if t.triage_notes:
            lines.append(f"Triage notes: {t.triage_notes}")
        if t.vital_flags:
            lines.append("Vital flag(s): " + ", ".join(t.vital_flags))
    except Exception:
        pass

    try:
        d = visit.disposition
        lines.append(f"Disposition decided: {d.get_disposition_display()}")
        if d.disposition_notes:
            lines.append(f"Disposition notes: {d.disposition_notes}")
    except Exception:
        pass

    if visit.attending_physician:
        lines.append(f"Attending: {visit.attending_physician.get_full_name() or visit.attending_physician.username}")

    user_content = "\n".join(lines)

    try:
        from django.conf import settings
        deployment = getattr(settings, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": HANDOVER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=600,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return SBARNote(
            situation=data.get("situation", ""),
            background=data.get("background", ""),
            assessment=data.get("assessment", ""),
            recommendation=data.get("recommendation", ""),
        )
    except json.JSONDecodeError as exc:
        logger.error("Handover AI returned non-JSON: %s", exc)
        return SBARNote(error="AI returned invalid JSON")
    except Exception as exc:
        logger.error("Handover AI call failed: %s", exc)
        return SBARNote(error=str(exc))


def generate_all_sbar(shift, visits, user) -> dict[int, SBARNote]:
    """Generate SBAR for each visit in bulk. Returns {visit_pk: SBARNote}."""
    results = {}
    for visit in visits:
        results[visit.pk] = generate_sbar(visit)
    return results
