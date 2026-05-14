"""Structured import helpers for turning a finalized scribe session into EMR defaults.

The goal is not to silently "complete the chart" from free text. Instead, this
module extracts the low-risk, explicitly stated details we can recognize
deterministically and packages them as review-first suggestions for the EMR
encounter editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from scribe.models import ScribeSession

from ..constants import COMMON_DRUGS, COMMON_ICD10_CODES


ICD10_LABELS = {code: label for code, label in COMMON_ICD10_CODES}
COMMON_DRUG_INDEX = {
    item["generic"].lower(): item
    for item in COMMON_DRUGS
}
COMMON_BRAND_INDEX = {
    item["brand"].lower(): item
    for item in COMMON_DRUGS
    if item.get("brand")
}

DIAGNOSIS_MATCHERS = [
    {
        "code": "I10",
        "keywords": ["hypertension", "high blood pressure", "bp review", "blood pressure review"],
        "condition_keys": {"htn"},
    },
    {
        "code": "E11.9",
        "keywords": ["type 2 diabetes", "diabetes mellitus", "diabetes", "blood sugar review"],
        "condition_keys": {"dm"},
    },
    {
        "code": "J06.9",
        "keywords": ["upper respiratory infection", "uri", "common cold"],
        "condition_keys": set(),
    },
    {
        "code": "K52.9",
        "keywords": ["gastroenteritis", "gastroenteritis and colitis", "stomach virus"],
        "condition_keys": set(),
    },
    {
        "code": "J45.909",
        "keywords": ["asthma", "wheeze"],
        "condition_keys": {"asthma"},
    },
    {
        "code": "E78.5",
        "keywords": ["hyperlipidaemia", "hyperlipidemia", "high cholesterol", "dyslipidaemia", "dyslipidemia"],
        "condition_keys": {"lipids"},
    },
    {
        "code": "N39.0",
        "keywords": ["urinary tract infection", "uti"],
        "condition_keys": set(),
    },
    {
        "code": "Z34.9",
        "keywords": ["normal pregnancy", "pregnancy follow-up", "antenatal visit", "prenatal visit"],
        "condition_keys": set(),
    },
]

HERBAL_KEYWORDS = [
    "cerasee",
    "soursop leaf",
    "fever grass",
    "moringa",
    "bush tea",
    "guaco",
    "herbal",
]

ROUTE_MAP = {
    "oral": "oral",
    "po": "oral",
    "iv": "IV",
    "intravenous": "IV",
    "im": "IM",
    "intramuscular": "IM",
    "sc": "SC",
    "subcutaneous": "SC",
    "topical": "topical",
    "inhaled": "inhaled",
    "inhaler": "inhaled",
    "sublingual": "sublingual",
    "rectal": "rectal",
    "ophthalmic": "ophthalmic",
}

FREQUENCY_PATTERNS = [
    "once daily",
    "twice daily",
    "three times daily",
    "four times daily",
    "daily",
    "bid",
    "tds",
    "qds",
    "prn",
    "at night",
    "every morning",
    "every evening",
]

VITAL_PREVIEW_LABELS = [
    ("bp_systolic", "BP systolic"),
    ("bp_diastolic", "BP diastolic"),
    ("pulse_bpm", "Pulse"),
    ("respiratory_rate", "Respiratory rate"),
    ("temperature_celsius", "Temperature"),
    ("oxygen_saturation", "SpO2"),
    ("blood_glucose_mmol", "Blood glucose"),
    ("weight_kg", "Weight"),
    ("height_cm", "Height"),
    ("muac_cm", "MUAC"),
    ("pain_score", "Pain score"),
    ("head_circumference_cm", "Head circumference"),
]


@dataclass
class ScribeImportBundle:
    encounter_initial: dict = field(default_factory=dict)
    vitals_initial: dict = field(default_factory=dict)
    diagnosis_initial: list[dict] = field(default_factory=list)
    medication_initial: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    vitals_preview: list[dict] = field(default_factory=list)
    diagnosis_preview: list[dict] = field(default_factory=list)
    medication_preview: list[dict] = field(default_factory=list)

    @property
    def has_structured_content(self) -> bool:
        return any(
            [
                self.vitals_initial,
                self.diagnosis_initial,
                self.medication_initial,
                self.flags,
                self.key_phrases,
            ]
        )

    def add_flag(self, message: str) -> None:
        if message and message not in self.flags:
            self.flags.append(message)

    def add_phrase(self, text: str) -> None:
        clean = re.sub(r"\s+", " ", (text or "")).strip(" -.;")
        if clean and clean not in self.key_phrases:
            self.key_phrases.append(clean)


def build_scribe_import_bundle(
    session: ScribeSession,
    *,
    encounter_date: date | None = None,
) -> ScribeImportBundle:
    """Build structured EMR defaults from a scribe session and its note."""

    note = getattr(session, "note", None)
    encounter_date = encounter_date or timezone.localdate()
    bundle = ScribeImportBundle()

    subjective_text = _join_texts(session.chief_complaint, note.subjective if note else "", session.transcript)
    objective_text = _join_texts(note.objective if note else "", session.transcript)
    assessment_text = _join_texts(note.assessment if note else "", session.transcript, session.title)
    plan_text = _join_texts(note.plan if note else "", note.edited_note if note else "", note.full_note if note else "", session.transcript)
    full_text = _join_texts(session.title, session.chief_complaint, session.transcript, subjective_text, objective_text, assessment_text, plan_text)

    bundle.encounter_initial = _build_encounter_initial(
        session=session,
        note=note,
        subjective_text=subjective_text,
        full_text=full_text,
        plan_text=plan_text,
        assessment_text=assessment_text,
        encounter_date=encounter_date,
        bundle=bundle,
    )
    bundle.vitals_initial = _extract_vitals(objective_text, encounter_date=encounter_date, bundle=bundle)
    bundle.diagnosis_initial = _extract_diagnoses(
        session=session,
        assessment_text=assessment_text,
        full_text=full_text,
    )
    bundle.medication_initial = _extract_medications(plan_text, session.transcript)
    bundle.vitals_preview = _build_vitals_preview(bundle.vitals_initial)
    bundle.diagnosis_preview = _build_diagnosis_preview(bundle.diagnosis_initial)
    bundle.medication_preview = _build_medication_preview(bundle.medication_initial)
    return bundle


def _build_encounter_initial(
    *,
    session: ScribeSession,
    note,
    subjective_text: str,
    full_text: str,
    plan_text: str,
    assessment_text: str,
    encounter_date: date,
    bundle: ScribeImportBundle,
) -> dict:
    initial = {
        "chief_complaint": session.chief_complaint or (note.subjective[:120] if note and note.subjective else ""),
        "history_of_presenting_illness": note.subjective if note else "",
        "physical_examination": note.objective if note else "",
        "assessment_notes": note.assessment if note else "",
        "plan_notes": (note.plan or note.edited_note or note.full_note) if note else "",
        "scribe_session": session,
    }

    encounter_type = _detect_encounter_type(full_text, session.active_conditions)
    if encounter_type:
        initial["encounter_type"] = encounter_type

    review_of_systems = _extract_review_of_systems(subjective_text)
    if review_of_systems:
        initial["review_of_systems"] = review_of_systems

    follow_up_date, follow_up_phrase = _extract_follow_up_date(plan_text, encounter_date)
    if follow_up_date:
        initial["follow_up_date"] = follow_up_date
        bundle.add_phrase(follow_up_phrase)

    follow_up_instructions = _extract_follow_up_instructions(plan_text)
    if follow_up_instructions:
        initial["follow_up_instructions"] = follow_up_instructions
        for sentence in _split_sentences(follow_up_instructions):
            bundle.add_phrase(sentence)

    sick_leave = _extract_sick_leave(plan_text, encounter_date, assessment_text, session.chief_complaint)
    if sick_leave:
        initial.update(sick_leave)
        if sick_leave.get("_phrase"):
            bundle.add_phrase(sick_leave["_phrase"])
        initial.pop("_phrase", None)

    herbal_remedies = _extract_herbal_remedies(full_text)
    if herbal_remedies:
        initial["herbal_remedies"] = herbal_remedies
        for sentence in _split_sentences(herbal_remedies):
            bundle.add_phrase(sentence)

    return {key: value for key, value in initial.items() if value not in (None, "", [], {})}


def _extract_vitals(text: str, *, encounter_date: date, bundle: ScribeImportBundle) -> dict:
    del encounter_date  # reserved for future time-relative parsing
    vitals: dict = {}

    bp_match = _last_match(
        r"\b(?:blood pressure|bp)\b[^\d]{0,20}(\d{2,3})\s*(?:/|over)\s*(\d{2,3})\b",
        text,
    )
    if bp_match:
        vitals["bp_systolic"] = int(bp_match.group(1))
        vitals["bp_diastolic"] = int(bp_match.group(2))
        bundle.add_phrase(_phrase_for_match(text, bp_match))

    pulse_match = _last_match(
        r"\b(?:heart rate|pulse)\b[^\d]{0,20}(\d{2,3}(?:\.\d+)?)\b",
        text,
    )
    if pulse_match:
        vitals["pulse_bpm"] = int(Decimal(pulse_match.group(1)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        bundle.add_phrase(_phrase_for_match(text, pulse_match))

    respiratory_match = _last_match(
        r"\b(?:respiratory rate|resp rate|respirations?)\b[^\d]{0,20}(\d{1,3})\b",
        text,
    )
    if respiratory_match:
        vitals["respiratory_rate"] = int(respiratory_match.group(1))
        bundle.add_phrase(_phrase_for_match(text, respiratory_match))

    temperature_match = _last_match(
        r"\b(?:temperature|temp)\b[^\d]{0,20}(\d{2,3}(?:\.\d+)?)\s*(?:°?\s*([cCfF])|celsius|fahrenheit)?",
        text,
    )
    if temperature_match:
        value = Decimal(temperature_match.group(1))
        unit_token = (temperature_match.group(2) or "").lower()
        if unit_token == "f" or "fahrenheit" in temperature_match.group(0).lower():
            value = _round_decimal((value - Decimal("32")) * Decimal("5") / Decimal("9"))
            bundle.add_flag("Temperature was spoken in Fahrenheit and converted to Celsius for the EMR.")
        vitals["temperature_celsius"] = value
        bundle.add_phrase(_phrase_for_match(text, temperature_match))

    spo2_match = _last_match(
        r"\b(?:spo2|spO2|oxygen saturation|o2 sat(?:uration)?|sats?)\b[^\d]{0,20}(\d{2,3}(?:\.\d+)?)\s*%?",
        text,
    )
    if spo2_match:
        vitals["oxygen_saturation"] = _round_decimal(Decimal(spo2_match.group(1)))
        bundle.add_phrase(_phrase_for_match(text, spo2_match))

    glucose_match = _last_match(
        r"\b(?:blood glucose|blood sugar|glucose|sugar)\b[^\d]{0,20}(\d{1,3}(?:\.\d+)?)\s*(mmol\/?l|mmol|mg\/?dl)?",
        text,
    )
    if glucose_match:
        glucose_value = Decimal(glucose_match.group(1))
        glucose_unit = (glucose_match.group(2) or "").lower()
        if "mg" in glucose_unit:
            glucose_value = _round_decimal(glucose_value / Decimal("18"))
            bundle.add_flag("Blood glucose was spoken in mg/dL and converted to mmol/L for the EMR.")
            vitals["blood_glucose_mmol"] = glucose_value
        elif "mmol" in glucose_unit:
            vitals["blood_glucose_mmol"] = _round_decimal(glucose_value)
        elif glucose_value <= Decimal("25"):
            vitals["blood_glucose_mmol"] = _round_decimal(glucose_value)
            bundle.add_flag("Blood glucose unit was not spoken; mmol/L was assumed for review.")
        else:
            bundle.add_flag("A blood glucose value was heard without a clear unit and was left out of the form.")
        bundle.add_phrase(_phrase_for_match(text, glucose_match))

    pain_match = _last_match(
        r"\b(?:pain score|pain(?: level)?|pain scale)\b[^\d]{0,20}(\d{1,2})(?:\s*/\s*10|\s+out of\s+10)?",
        text,
    )
    if pain_match:
        pain_value = int(pain_match.group(1))
        if 0 <= pain_value <= 10:
            vitals["pain_score"] = pain_value
            bundle.add_phrase(_phrase_for_match(text, pain_match))

    weight_match = _last_match(
        r"\bweight\b[^\d]{0,20}(\d{1,3}(?:\.\d+)?)\s*(kg|kilograms?|lb|lbs|pounds?)",
        text,
    )
    if weight_match:
        value = Decimal(weight_match.group(1))
        unit = weight_match.group(2).lower()
        if unit.startswith("lb") or unit.startswith("pound"):
            value = _round_decimal(value * Decimal("0.453592"))
            bundle.add_flag("Weight was spoken in pounds and converted to kilograms for the EMR.")
        vitals["weight_kg"] = value
        bundle.add_phrase(_phrase_for_match(text, weight_match))

    height_match = _last_match(
        r"\bheight\b[^\d]{0,20}(\d{1,3}(?:\.\d+)?)\s*(cm|centimeters?|m|meters?)",
        text,
    )
    if height_match:
        value = Decimal(height_match.group(1))
        unit = height_match.group(2).lower()
        if unit.startswith("m") and not unit.startswith("cm"):
            value = _round_decimal(value * Decimal("100"))
            bundle.add_flag("Height was spoken in meters and converted to centimeters for the EMR.")
        vitals["height_cm"] = value
        bundle.add_phrase(_phrase_for_match(text, height_match))

    muac_match = _last_match(
        r"\b(?:muac|mid[- ]upper arm circumference)\b[^\d]{0,20}(\d{1,3}(?:\.\d+)?)\s*(?:cm)?",
        text,
    )
    if muac_match:
        vitals["muac_cm"] = _round_decimal(Decimal(muac_match.group(1)))
        bundle.add_phrase(_phrase_for_match(text, muac_match))

    head_match = _last_match(
        r"\b(?:head circumference|hc)\b[^\d]{0,20}(\d{1,3}(?:\.\d+)?)\s*(?:cm)?",
        text,
    )
    if head_match:
        vitals["head_circumference_cm"] = _round_decimal(Decimal(head_match.group(1)))
        bundle.add_phrase(_phrase_for_match(text, head_match))

    return vitals


def _extract_diagnoses(*, session: ScribeSession, assessment_text: str, full_text: str) -> list[dict]:
    matches = []
    lowered_assessment = assessment_text.lower()
    lowered_full_text = full_text.lower()
    condition_keys = {item.strip().lower() for item in (session.active_conditions or "").split(",") if item.strip()}

    for matcher in DIAGNOSIS_MATCHERS:
        earliest_index = None
        source_sentence = ""
        for keyword in matcher["keywords"]:
            index = lowered_assessment.find(keyword)
            if index == -1:
                index = lowered_full_text.find(keyword)
            if index != -1 and (earliest_index is None or index < earliest_index):
                earliest_index = index
                source_sentence = _sentence_containing(full_text, keyword)

        if earliest_index is None and matcher["condition_keys"] and matcher["condition_keys"] & condition_keys:
            earliest_index = 10_000 + len(matches)
            source_sentence = f"Active conditions include {', '.join(sorted(matcher['condition_keys'] & condition_keys))}."

        if earliest_index is None:
            continue

        description = ICD10_LABELS[matcher["code"]]
        status = _diagnosis_status_for_text(lowered_full_text, description)
        matches.append(
            {
                "order": earliest_index,
                "payload": {
                    "icd10_code": matcher["code"],
                    "icd10_description": description,
                    "status": status,
                    "diagnosis_rank": len(matches) + 1,
                    "notes": source_sentence,
                },
            }
        )

    ordered = sorted(matches, key=lambda item: item["order"])
    return [item["payload"] for item in ordered]


def _extract_medications(plan_text: str, transcript_text: str) -> list[dict]:
    medication_rows = []
    seen_generics = set()
    sentences = _split_sentences(_join_texts(plan_text, transcript_text))

    for sentence in sentences:
        lowered_sentence = sentence.lower()
        if not _sentence_has_medication_cue(lowered_sentence) and lowered_sentence not in plan_text.lower():
            continue

        for generic_key, drug in COMMON_DRUG_INDEX.items():
            brand_key = (drug.get("brand") or "").lower()
            if generic_key not in lowered_sentence and (not brand_key or brand_key not in lowered_sentence):
                continue

            if generic_key in seen_generics:
                continue

            row = {
                "drug_name_generic": drug["generic"],
                "drug_name_brand": drug.get("brand", ""),
                "pharmacy_instructions": sentence.strip(),
            }

            dose_match = re.search(
                rf"\b(?:{re.escape(drug['generic'])}|{re.escape(drug.get('brand', ''))})\b[^\d]{{0,10}}(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)",
                sentence,
                flags=re.IGNORECASE,
            )
            if dose_match:
                row["dose_amount"] = Decimal(dose_match.group(1))
                row["dose_unit"] = dose_match.group(2).lower()

            route = _extract_route(sentence)
            if route:
                row["route"] = route

            frequency = _extract_frequency(sentence)
            if frequency:
                row["frequency"] = frequency

            duration_days = _extract_duration_days(sentence)
            if duration_days is not None:
                row["duration_days"] = duration_days

            medication_rows.append(row)
            seen_generics.add(generic_key)

    return medication_rows


def _build_vitals_preview(vitals_initial: dict) -> list[dict]:
    preview = []
    for key, label in VITAL_PREVIEW_LABELS:
        if key not in vitals_initial:
            continue
        value = vitals_initial[key]
        if key == "temperature_celsius":
            display = f"{value} C"
        elif key == "oxygen_saturation":
            display = f"{value}%"
        elif key == "blood_glucose_mmol":
            display = f"{value} mmol/L"
        elif key == "weight_kg":
            display = f"{value} kg"
        elif key in {"height_cm", "muac_cm", "head_circumference_cm"}:
            display = f"{value} cm"
        elif key == "pain_score":
            display = f"{value}/10"
        else:
            display = str(value)
        preview.append({"label": label, "value": display})
    return preview


def _build_diagnosis_preview(diagnosis_initial: list[dict]) -> list[dict]:
    return [
        {
            "label": item["icd10_code"],
            "value": item["icd10_description"],
            "notes": item.get("notes", ""),
        }
        for item in diagnosis_initial
    ]


def _build_medication_preview(medication_initial: list[dict]) -> list[dict]:
    preview = []
    for item in medication_initial:
        bits = []
        if item.get("dose_amount"):
            bits.append(str(item["dose_amount"]).rstrip("0").rstrip("."))
        if item.get("dose_unit"):
            bits.append(item["dose_unit"])
        if item.get("frequency"):
            bits.append(item["frequency"])
        if item.get("duration_days"):
            bits.append(f"{item['duration_days']} days")
        preview.append(
            {
                "label": item["drug_name_generic"],
                "value": " ".join(bits).strip(),
                "notes": item.get("pharmacy_instructions", ""),
            }
        )
    return preview


def _detect_encounter_type(full_text: str, active_conditions: str) -> str:
    lowered = full_text.lower()
    condition_keys = {item.strip().lower() for item in (active_conditions or "").split(",") if item.strip()}
    if any(word in lowered for word in ["antenatal", "pregnancy", "prenatal"]):
        return "antenatal"
    if any(word in lowered for word in ["immunization", "immunisation", "vaccine", "vaccination"]):
        return "immunisation"
    if any(word in lowered for word in ["well child", "routine child", "growth check"]):
        return "well_child"
    if any(word in lowered for word in ["home visit", "visited at home"]):
        return "home_visit"
    if any(word in lowered for word in ["telehealth", "phone consult", "video visit"]):
        return "telehealth"
    if any(word in lowered for word in ["follow up", "follow-up", "bp review", "review visit"]) or condition_keys:
        if any(key in condition_keys for key in {"htn", "dm", "lipids", "asthma", "ckd"}):
            return "chronic_followup"
    return ""


def _extract_review_of_systems(text: str) -> str:
    ros_sentences = []
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if "denies" in lowered or "negative for" in lowered:
            ros_sentences.append(sentence.strip())
            continue
        if re.search(
            r"\bno\s+(fever|cough|chest pain|shortness of breath|vomiting|diarrhea|diarrhoea|dysuria|rash|wheeze)\b",
            lowered,
        ):
            ros_sentences.append(sentence.strip())
    if not ros_sentences:
        return ""
    unique_sentences = []
    for sentence in ros_sentences:
        if sentence not in unique_sentences:
            unique_sentences.append(sentence)
    return "\n".join(f"- {sentence}" for sentence in unique_sentences)


def _extract_follow_up_date(text: str, encounter_date: date) -> tuple[date | None, str]:
    match = _last_match(
        r"\b(?:follow up|follow-up|review|return)\s+(?:in|after)\s+(\d+)\s+(day|days|week|weeks|month|months)\b",
        text,
    )
    if not match:
        return None, ""
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("day"):
        delta = timedelta(days=amount)
    elif unit.startswith("week"):
        delta = timedelta(weeks=amount)
    else:
        delta = timedelta(days=amount * 30)
    return encounter_date + delta, _phrase_for_match(text, match)


def _extract_follow_up_instructions(text: str) -> str:
    sentences = []
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(
            cue in lowered
            for cue in [
                "follow up",
                "follow-up",
                "return if",
                "return to clinic",
                "advised to",
                "advise to",
                "encouraged to",
                "rest",
                "hydrate",
                "continue",
            ]
        ):
            sentences.append(sentence.strip())
    unique_sentences = []
    for sentence in sentences:
        if sentence not in unique_sentences:
            unique_sentences.append(sentence)
    return " ".join(unique_sentences)


def _extract_sick_leave(
    text: str,
    encounter_date: date,
    assessment_text: str,
    chief_complaint: str,
) -> dict:
    match = _last_match(
        r"\b(?:sick leave|medical leave|off work)\b[^\d]{0,20}(\d+)\s+(day|days|week|weeks)\b",
        text,
    )
    if not match:
        match = _last_match(
            r"\b(\d+)\s+(day|days|week|weeks)\s+(?:of\s+)?(?:sick leave|medical leave|off work)\b",
            text,
        )
    if not match:
        return {}
    amount = int(match.group(1))
    unit = match.group(2).lower()
    total_days = amount * 7 if unit.startswith("week") else amount
    diagnosis_text = _first_non_empty_line(assessment_text) or chief_complaint
    return {
        "sick_leave_start": encounter_date,
        "sick_leave_end": encounter_date + timedelta(days=max(total_days - 1, 0)),
        "sick_leave_diagnosis": diagnosis_text[:200] if diagnosis_text else "",
        "_phrase": _phrase_for_match(text, match),
    }


def _extract_herbal_remedies(text: str) -> str:
    matched_sentences = []
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in HERBAL_KEYWORDS):
            matched_sentences.append(sentence.strip())
    unique_sentences = []
    for sentence in matched_sentences:
        if sentence not in unique_sentences:
            unique_sentences.append(sentence)
    return " ".join(unique_sentences)


def _extract_route(sentence: str) -> str:
    lowered = sentence.lower()
    for token, normalized in ROUTE_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return normalized
    return ""


def _extract_frequency(sentence: str) -> str:
    lowered = sentence.lower()
    for frequency in FREQUENCY_PATTERNS:
        if frequency in lowered:
            return frequency
    return ""


def _extract_duration_days(sentence: str) -> int | None:
    match = re.search(
        r"\b(?:for|x)\s+(\d+)\s+(day|days|week|weeks|month|months)\b",
        sentence,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("day"):
        return amount
    if unit.startswith("week"):
        return amount * 7
    return amount * 30


def _sentence_has_medication_cue(lowered_sentence: str) -> bool:
    return any(
        cue in lowered_sentence
        for cue in [
            "start ",
            "continue",
            "prescribe",
            "take ",
            "given ",
            "medication",
            "tablet",
            "capsule",
        ]
    )


def _diagnosis_status_for_text(text: str, description: str) -> str:
    description_lower = description.lower()
    if any(word in text for word in ["history of", "known", "longstanding", "chronic", "follow-up"]):
        if any(word in description_lower for word in ["hypertension", "diabetes", "hyperlip", "asthma"]):
            return "chronic"
    if any(word in text for word in ["possible", "suspected", "query "]):
        return "suspected"
    return "active"


def _sentence_containing(text: str, keyword: str) -> str:
    for sentence in _split_sentences(text):
        if keyword.lower() in sentence.lower():
            return sentence.strip()
    return ""


def _first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        clean = line.strip(" -:\t")
        if clean:
            return clean
    return ""


def _join_texts(*parts: str) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _split_sentences(text: str) -> list[str]:
    raw_parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [part.strip() for part in raw_parts if part and part.strip()]


def _last_match(pattern: str, text: str):
    matches = list(re.finditer(pattern, text or "", flags=re.IGNORECASE))
    if not matches:
        return None
    return matches[-1]


def _phrase_for_match(text: str, match) -> str:
    return _sentence_around_span(text, match.start(), match.end()) or match.group(0)


def _sentence_around_span(text: str, start: int, end: int) -> str:
    if not text:
        return ""
    left = text.rfind(".", 0, start)
    left_newline = text.rfind("\n", 0, start)
    left = max(left, left_newline)
    right_period = text.find(".", end)
    right_newline = text.find("\n", end)
    right_candidates = [position for position in [right_period, right_newline] if position != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left + 1 : right].strip()


def _round_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
