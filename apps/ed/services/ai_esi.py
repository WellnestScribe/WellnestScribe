"""AI-assisted ESI triage scoring and red-flag detection.

Uses the same Azure OpenAI / OpenAI client as the scribe app.
Returns a structured result rather than raw text so the caller can
display the suggestion, flags, and rationale separately.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

ESI_SYSTEM_PROMPT = """\
You are a clinical decision support tool for an Emergency Department triage system.
Your role is to suggest an Emergency Severity Index (ESI) level based on the patient
data provided. You assist the triage nurse — you do NOT replace their clinical judgement.

ESI Levels:
1 = Requires immediate life-saving intervention (airway, breathing, circulation threat)
2 = High-risk situation OR severe pain/distress that cannot wait
3 = Stable but needs 2+ resources (labs, imaging, IV, specialist)
4 = Stable, needs 1 resource
5 = No resources needed (primary care presentation)

Respond ONLY with valid JSON in this exact format:
{
  "esi": <integer 1-5>,
  "rationale": "<1-2 sentence clinical rationale>",
  "flags": ["<red flag 1>", "<red flag 2>"],
  "confidence": "<high|moderate|low>"
}

flags: list specific vital sign abnormalities or clinical red flags driving the decision.
If no flags, return an empty list [].
Do not include any text outside the JSON object.
"""


@dataclass
class ESISuggestion:
    esi: int
    rationale: str
    flags: list[str] = field(default_factory=list)
    confidence: str = "moderate"
    error: str = ""


def suggest_esi(
    chief_complaint: str,
    mechanism: str = "medical",
    temp_celsius: float | None = None,
    bp_systolic: int | None = None,
    bp_diastolic: int | None = None,
    pulse_bpm: int | None = None,
    rr_rpm: int | None = None,
    spo2_percent: float | None = None,
    pain_score: int | None = None,
    gcs_total: int | None = None,
    pmh_list: list[str] | None = None,
    age: int | None = None,
) -> ESISuggestion:
    """Call AI to get an ESI suggestion. Returns ESISuggestion (never raises)."""
    try:
        from scribe.services.clients import get_chat_client, AIConfigError
        client = get_chat_client()
    except Exception as exc:
        logger.warning("AI client unavailable for ESI suggestion: %s", exc)
        return ESISuggestion(esi=3, rationale="", flags=[], error=str(exc))

    vitals_parts = []
    if pulse_bpm is not None:
        vitals_parts.append(f"HR {pulse_bpm} bpm")
    if bp_systolic and bp_diastolic:
        vitals_parts.append(f"BP {bp_systolic}/{bp_diastolic} mmHg")
    if rr_rpm is not None:
        vitals_parts.append(f"RR {rr_rpm}/min")
    if temp_celsius is not None:
        vitals_parts.append(f"Temp {temp_celsius}°C")
    if spo2_percent is not None:
        vitals_parts.append(f"SpO₂ {spo2_percent}%")
    if pain_score is not None:
        vitals_parts.append(f"Pain {pain_score}/10")
    if gcs_total is not None:
        vitals_parts.append(f"GCS {gcs_total}/15")

    user_lines = [
        f"Chief complaint: {chief_complaint}",
        f"Mechanism: {mechanism}",
    ]
    if age:
        user_lines.append(f"Patient age: {age} years")
    if vitals_parts:
        user_lines.append("Vitals: " + ", ".join(vitals_parts))
    if pmh_list:
        user_lines.append("Past medical history: " + ", ".join(pmh_list))

    user_content = "\n".join(user_lines)

    try:
        deployment = getattr(settings, "SCRIBE_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": ESI_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=400,
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        esi = int(data.get("esi", 3))
        if not (1 <= esi <= 5):
            esi = 3
        return ESISuggestion(
            esi=esi,
            rationale=data.get("rationale", ""),
            flags=data.get("flags", []),
            confidence=data.get("confidence", "moderate"),
        )
    except json.JSONDecodeError as exc:
        logger.error("ESI AI returned non-JSON: %s", exc)
        return ESISuggestion(esi=3, rationale="", error="AI returned invalid JSON")
    except Exception as exc:
        logger.error("ESI AI call failed: %s", exc)
        return ESISuggestion(esi=3, rationale="", error=str(exc))
