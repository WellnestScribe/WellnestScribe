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
    # Diagnoses are coded ONLY from the clinician's written note (Assessment /
    # Plan / Subjective), never from the raw transcript or the patient's verbatim
    # chief complaint. A coded diagnosis asserts the patient HAS the condition, so
    # it must come from what the doctor documented - not from a stray word the
    # patient said. Negation, family history and uncertainty are filtered in
    # _extract_diagnoses below.
    diagnosis_source = _join_texts(
        note.assessment if note else "",
        note.plan if note else "",
        note.subjective if note else "",
    )
    if not diagnosis_source and note:
        diagnosis_source = note.edited_note or note.full_note or ""
    # Primary path: use the ICD-10 codes the model attached to the doctor's
    # Assessment (context-aware, respects doctor-vs-patient). Fall back to the
    # deterministic keyword extractor only for older notes with no ICD tags.
    ai_coded = _parse_ai_coded_diagnoses(diagnosis_source, bundle)
    if ai_coded:
        bundle.diagnosis_initial = ai_coded
    else:
        bundle.diagnosis_initial = _extract_diagnoses(
            session=session,
            source_text=diagnosis_source,
            bundle=bundle,
        )
    bundle.medication_initial = _extract_medications(plan_text, session.transcript)
    bundle.vitals_preview = _build_vitals_preview(bundle.vitals_initial)
    bundle.diagnosis_preview = _build_diagnosis_preview(bundle.diagnosis_initial)
    bundle.medication_preview = _build_medication_preview(bundle.medication_initial)
    return bundle


def materialize_encounter_from_session(session, user):
    """Auto-create/populate an EMR encounter from a finalized scribe session.

    This is the automatic version of "import from scribe": when the doctor
    finalizes the note, we deterministically extract the structured data and
    write it straight into the patient's encounter (reusing today's intake
    encounter if one exists), link the scribe session + provider, and leave it
    as a DRAFT for the clinician to review and sign. No AI, no manual re-linking.

    Best-effort and idempotent-ish: never overwrites a signed encounter, never
    clobbers an encounter already owned by a different scribe session, and skips
    duplicate diagnoses/medications/vitals. Returns the Encounter, or None.
    """
    from django.utils import timezone as _tz

    from emr.models import Diagnosis, Encounter, Medication, Vital
    from emr.services.access import get_membership

    patient = getattr(session, "patient", None)
    if patient is None:
        return None
    org = get_membership(session.doctor).organisation
    if patient.organisation_id != org.pk:
        return None

    today = _tz.localdate()
    enc = (
        Encounter.objects.filter(patient=patient, organisation=org, encounter_date=today)
        .exclude(encounter_status="signed")
        .order_by("-created_at")
        .first()
    )
    if enc is not None and enc.scribe_session_id and enc.scribe_session_id != session.pk:
        return enc  # a different note already owns this encounter — leave it

    bundle = build_scribe_import_bundle(session, encounter_date=today)
    ei = bundle.encounter_initial

    if enc is None:
        enc = Encounter(organisation=org, patient=patient, encounter_date=today, created_by=user)
    enc.scribe_session = session
    if enc.provider_id is None:
        enc.provider = user
    for f in (
        "chief_complaint", "history_of_presenting_illness", "physical_examination",
        "assessment_notes", "plan_notes", "review_of_systems",
        "follow_up_instructions", "herbal_remedies", "sick_leave_diagnosis",
    ):
        if ei.get(f):
            setattr(enc, f, ei[f])
    for f in ("encounter_type", "follow_up_date", "sick_leave_start", "sick_leave_end"):
        if ei.get(f):
            setattr(enc, f, ei[f])
    if enc.created_by_id is None:
        enc.created_by = user
    enc.updated_by = user
    if not enc.encounter_status or enc.encounter_status not in {"signed"}:
        enc.encounter_status = "draft"
    enc.save()

    if bundle.vitals_initial and not Vital.objects.filter(encounter=enc).exists():
        vital = Vital(organisation=org, patient=patient, encounter=enc, recorded_by=user)
        for key, value in bundle.vitals_initial.items():
            setattr(vital, key, value)
        vital.save()

    existing_codes = set(Diagnosis.objects.filter(encounter=enc).values_list("icd10_code", flat=True))
    for d in bundle.diagnosis_initial:
        if d["icd10_code"] in existing_codes:
            continue
        Diagnosis.objects.create(
            organisation=org, patient=patient, encounter=enc,
            icd10_code=d["icd10_code"], icd10_description=d.get("icd10_description", ""),
            status=d.get("status", "active"), diagnosis_rank=d.get("diagnosis_rank", 1),
            notes=d.get("notes", ""), diagnosing_provider=user, ai_suggested=True,
        )

    existing_meds = set(Medication.objects.filter(encounter=enc).values_list("drug_name_generic", flat=True))
    for m in bundle.medication_initial:
        if m["drug_name_generic"] in existing_meds:
            continue
        Medication.objects.create(
            organisation=org, patient=patient, encounter=enc,
            drug_name_generic=m["drug_name_generic"], drug_name_brand=m.get("drug_name_brand", ""),
            dose_amount=m.get("dose_amount"), dose_unit=m.get("dose_unit", ""),
            route=m.get("route", ""), frequency=m.get("frequency", ""),
            duration_days=m.get("duration_days"), pharmacy_instructions=m.get("pharmacy_instructions", ""),
            prescribing_provider=user, ai_suggested=True,
        )

    return enc


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


# ── Diagnosis-safety guards ──────────────────────────────────────────────────
# A coded diagnosis is a legal assertion that THIS patient HAS the condition.
# We must never mint one from a denial ("denies diabetes"), someone else's
# history ("father has diabetes"), a resolved problem, or a coincidental
# substring ("uri" inside "during"). See docs/safety/diagnosis_extraction.md.

# Hard negation / absence -> do NOT code (surface as a review flag instead).
NEGATION_CUES = [
    "no known", "no history of", "no h/o", "not have", "does not have", "doesn't have",
    "denies", "denied", "deny", "negative for", "no evidence of", "without",
    "never had", "never", "nil", "absence of", "ruled out", "rules out",
    "free of", "resolved", "no longer", "nuh have", "nah have",
    "no", "not",
]
# Condition belongs to a relative, not the patient in front of us.
FAMILY_CUES = [
    "father", "mother", "mom", "mum", "dad", "brother", "sister", "sibling",
    "family history", "fam hx", "runs in the family", "aunt", "uncle",
    "grandmother", "grandfather", "grandparent", "parent", "cousin", "maternal",
    "paternal",
]
# Uncertain / differential -> code as "suspected", never "active"/"chronic".
SUSPECTED_CUES = [
    "possible", "probable", "suspected", "suspect", "query", "rule out", "r/o",
    "differential", "consider", "likely", "cannot exclude", "?",
]


def _has_cue(text: str, cues: list[str]) -> bool:
    """True if any cue appears in text. Pure alpha words are matched on word
    boundaries (so 'no' does not fire inside 'nostril'); phrases / punctuated
    cues fall back to substring."""
    for cue in cues:
        c = cue.strip().lower()
        if not c:
            continue
        if c.isalpha():
            if re.search(rf"\b{re.escape(c)}\b", text):
                return True
        elif c in text:
            return True
    return False


def _clause_around(sentence: str, keyword: str) -> str:
    """The clause containing keyword, bounded by conjunctions/commas so that a
    negation in a neighbouring clause ('no chest pain but has cough') does not
    leak across."""
    low = sentence.lower()
    idx = low.find(keyword.lower())
    if idx == -1:
        return sentence
    boundaries = [";", ",", " but ", " however ", " though ", " whereas ", " - ", " – "]
    start, end = 0, len(sentence)
    for b in boundaries:
        p = low.rfind(b, 0, idx)
        if p != -1:
            start = max(start, p + len(b))
        p2 = low.find(b, idx + len(keyword))
        if p2 != -1:
            end = min(end, p2)
    return sentence[start:end]


def _classify_diagnosis(sentence: str, keyword: str, description: str) -> tuple[str, str | None]:
    """Return (decision, status). decision is 'code' or 'skip'. When 'skip', the
    caller raises a review flag instead of silently coding OR silently dropping."""
    clause = _clause_around(sentence, keyword).lower()
    kidx = clause.find(keyword.lower())
    pre = clause[:kidx] if kidx != -1 else clause

    # Family history -> not this patient.
    if _has_cue(clause, FAMILY_CUES):
        return "skip", None
    # Hard negation before the term, or "resolved / ruled out / negative for" anywhere in the clause.
    if _has_cue(pre, NEGATION_CUES) or _has_cue(clause, ["ruled out", "rules out", "resolved", "no longer", "negative for"]):
        return "skip", None
    # Uncertainty -> suspected, not confirmed.
    if _has_cue(clause, SUSPECTED_CUES):
        return "code", "suspected"
    # Chronic vs active.
    desc_low = (description or "").lower()
    if _has_cue(clause, ["history of", "known", "longstanding", "chronic", "follow-up", "follow up"]):
        if any(w in desc_low for w in ["hypertension", "diabetes", "hyperlip", "asthma"]):
            return "code", "chronic"
    return "code", "active"


def _condition_denied_in_text(text: str, keywords: list[str]) -> bool:
    """Used for known/active conditions: is this condition explicitly negated in
    the current note? If so we flag a conflict rather than re-coding it."""
    low = (text or "").lower()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw.lower())}\b", low):
            decision, _ = _classify_diagnosis(_sentence_containing(text, kw), kw, "")
            if decision == "skip":
                return True
    return False


def _extract_diagnoses(*, session: ScribeSession, source_text: str, bundle: ScribeImportBundle) -> list[dict]:
    """Deterministically code diagnoses from the clinician's written note only.

    Safety rules (see docs/safety/diagnosis_extraction.md):
      1. Word-boundary matching  -> 'uri' can never fire inside 'during'.
      2. Negation guard          -> 'denies diabetes' is never coded.
      3. Family-history guard     -> 'father has diabetes' is never coded.
      4. Uncertainty -> suspected -> 'possible fracture' is not asserted as fact.
      5. Skips are surfaced as review flags, never silently dropped.
    """
    matches: list[dict] = []
    source_text = source_text or ""
    lowered = source_text.lower()
    condition_keys = {item.strip().lower() for item in (session.active_conditions or "").split(",") if item.strip()}

    for matcher in DIAGNOSIS_MATCHERS:
        description = ICD10_LABELS[matcher["code"]]

        earliest_index = None
        matched_keyword = ""
        source_sentence = ""
        for keyword in matcher["keywords"]:
            m = re.search(rf"\b{re.escape(keyword)}\b", lowered)
            if m and (earliest_index is None or m.start() < earliest_index):
                earliest_index = m.start()
                matched_keyword = keyword
                source_sentence = _sentence_containing(source_text, keyword)

        status: str | None
        if earliest_index is not None:
            decision, status = _classify_diagnosis(source_sentence, matched_keyword, description)
            if decision == "skip":
                bundle.add_flag(
                    f"'{description}' was mentioned but NOT auto-added to the Problem List "
                    f"— it appears negated, attributed to family history, or resolved "
                    f"(\"{_shorten(source_sentence)}\"). Add it manually only if the patient "
                    f"actually has it."
                )
                continue
            order = earliest_index
        elif matcher["condition_keys"] and (matcher["condition_keys"] & condition_keys):
            # Known chronic condition on file. Honour it unless THIS visit denies it.
            if _condition_denied_in_text(source_text, matcher["keywords"]):
                bundle.add_flag(
                    f"'{description}' is on the patient's known-conditions list but appears "
                    f"to be denied in this visit — confirm before keeping it on the Problem List."
                )
                continue
            order = 10_000 + len(matches)
            source_sentence = f"Known condition on file ({', '.join(sorted(matcher['condition_keys'] & condition_keys))})."
            status = "chronic" if any(w in description.lower() for w in ["hypertension", "diabetes", "hyperlip", "asthma"]) else "active"
        else:
            continue

        matches.append(
            {
                "order": order,
                "payload": {
                    "icd10_code": matcher["code"],
                    "icd10_description": description,
                    "status": status,
                    "notes": source_sentence,
                },
            }
        )

    ordered = sorted(matches, key=lambda item: item["order"])
    for rank, item in enumerate(ordered, start=1):
        item["payload"]["diagnosis_rank"] = rank
    return [item["payload"] for item in ordered]


def _shorten(text: str, limit: int = 90) -> str:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


# ── AI-coded diagnoses (primary path) ─────────────────────────────────────────
# The note generator tags each Assessment line the DOCTOR confirmed with its
# ICD-10 code, e.g. "1. Hypertension (uncontrolled) (ICD-10 I10)". The model -
# unlike a keyword regex - understands that a condition the patient merely
# mentioned or denied does NOT belong in the Assessment, so it never codes it.
# The doctor's Assessment is the ground truth. We parse those codes here; the
# keyword extractor is only a fallback for notes with no ICD tags.
_ICD10_TAG_RE = re.compile(r"\(\s*ICD-?10[:\s]+([A-Za-z0-9.\?]+)\s*\)", re.IGNORECASE)
_ICD10_VALID_RE = re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-Za-z]{1,4})?$")


def _status_from_line(desc: str) -> str:
    low = desc.lower()
    if _has_cue(low, SUSPECTED_CUES):
        return "suspected"
    if _has_cue(low, ["chronic", "known", "longstanding", "ongoing"]):
        return "chronic"
    return "active"


def _parse_ai_coded_diagnoses(text: str, bundle: ScribeImportBundle) -> list[dict]:
    """Build the Problem List from the ICD-10 tags the model attached to the
    doctor's Assessment. Returns [] when the note carries no tags (older notes),
    so the caller can fall back to the deterministic keyword extractor."""
    if not text:
        return []
    results: list[dict] = []
    seen_codes: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        m = _ICD10_TAG_RE.search(line)
        if not m:
            continue
        code = m.group(1).strip().upper().rstrip(".")
        desc = _ICD10_TAG_RE.sub("", line).strip()
        desc = re.sub(r"^\d+[.)]\s*", "", desc)              # strip leading "1. "
        desc = re.split(r"\s+[—–-]\s+", desc)[0].strip(" -–—.")  # concise name, drop explanation
        if not desc:
            continue
        valid = code != "?" and bool(_ICD10_VALID_RE.match(code))
        code = code if valid else ""
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        if not valid:
            bundle.add_flag(
                f"'{_shorten(desc)}' was diagnosed but its ICD-10 code needs to be entered by the clinician."
            )
        results.append({
            "icd10_code": code,
            "icd10_description": ICD10_LABELS.get(code) or desc,
            "status": _status_from_line(desc),
            "notes": line,  # provenance: the exact Assessment line
        })
    for rank, item in enumerate(results, start=1):
        item["diagnosis_rank"] = rank
    return results


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


# ── Imaging / investigation requisition (deterministic, no AI) ────────────────
# Used to pre-fill a scan / lab request sheet from what the clinician wrote in
# the Plan. Keyword match with word boundaries only - same safety discipline as
# the diagnosis extractor. This SUGGESTS a requisition for the doctor to review
# and print; it never orders anything on its own.
IMAGING_STUDIES = [
    ("Chest X-ray", ["chest x-ray", "chest xray", "cxr", "chest radiograph"]),
    ("X-ray", ["x-ray", "xray", "x ray", "radiograph"]),
    ("Abdominal ultrasound", ["abdominal ultrasound", "abdominal us"]),
    ("Pelvic ultrasound", ["pelvic ultrasound"]),
    ("Obstetric ultrasound", ["obstetric ultrasound", "dating scan", "anomaly scan", "growth scan", "antenatal scan"]),
    ("Ultrasound", ["ultrasound", "sonogram"]),
    ("CT scan", ["ct scan", "cat scan", "computed tomography"]),
    ("MRI", ["mri", "magnetic resonance"]),
    ("Echocardiogram", ["echocardiogram"]),
    ("ECG (12-lead)", ["ecg", "ekg", "electrocardiogram"]),
    ("Mammogram", ["mammogram", "mammography"]),
    ("DEXA (bone density)", ["dexa", "bone density"]),
    ("Doppler ultrasound", ["doppler"]),
    ("Spirometry / PFTs", ["spirometry", "lung function", "pulmonary function"]),
]
INVESTIGATIONS = [
    ("Complete blood count (CBC)", ["cbc", "fbc", "complete blood count", "full blood count"]),
    ("Urine culture", ["urine culture", "midstream urine"]),
    ("Urinalysis", ["urinalysis", "urine dipstick", "urine test"]),
    ("Fasting blood glucose", ["fasting blood glucose", "fasting glucose"]),
    ("HbA1c", ["hba1c", "glycated haemoglobin", "glycated hemoglobin"]),
    ("Lipid profile", ["lipid profile", "cholesterol panel", "fasting lipids"]),
    ("Liver function tests", ["liver function", "lft"]),
    ("Renal function / U&E", ["renal function", "urea and electrolytes", "creatinine"]),
    ("Thyroid function (TSH)", ["thyroid function", "thyroid panel", "tsh"]),
    ("Pregnancy test", ["pregnancy test", "beta hcg", "urine hcg"]),
    ("Malaria test", ["malaria test", "malaria smear"]),
    ("Dengue test", ["dengue test", "dengue ns1"]),
    ("Pap smear", ["pap smear", "cervical smear"]),
    ("Blood culture", ["blood culture"]),
    ("Biopsy", ["biopsy"]),
]


def extract_imaging_and_investigations(*texts: str) -> list[dict]:
    """Return [{study, category, context}] for imaging/labs mentioned in the note.

    Deterministic and word-boundary matched. Each result carries the sentence it
    was found in, so the doctor can verify the requisition before printing."""
    combined = _join_texts(*texts)
    lowered = combined.lower()
    out: list[dict] = []
    spans: list[tuple[int, int]] = []  # accepted match spans, to suppress overlaps
    # Specific labels are listed before generic ones ("Chest X-ray" before "X-ray"),
    # so a generic keyword whose match sits inside an already-accepted span is dropped.
    for category, catalogue in (("Imaging", IMAGING_STUDIES), ("Investigation", INVESTIGATIONS)):
        for label, keywords in catalogue:
            best = None
            for kw in keywords:
                m = re.search(rf"\b{re.escape(kw)}\b", lowered)
                if m and (best is None or m.start() < best.start()):
                    best = m
            if best is None:
                continue
            if any(s <= best.start() and best.end() <= e for s, e in spans):
                continue  # already covered by a more specific study
            spans.append((best.start(), best.end()))
            out.append({
                "study": label,
                "category": category,
                "context": _sentence_containing(combined, best.group(0)),
            })
    return out
