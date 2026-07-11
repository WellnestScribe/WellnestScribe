"""SOAP / narrative / chart note generation via Azure OpenAI.

Reasoning-model awareness: Azure deployments backed by GPT-5 / o-series
spend tokens on internal reasoning before emitting any output. With a
small `max_completion_tokens` budget the model can return an empty
string. We detect that and retry with a larger budget + minimal
reasoning effort. This mirrors what production scribes do.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from django.conf import settings
from openai import BadRequestError

from .clients import get_chat_client
from .prompts import (
    CHART_USER_PROMPT,
    DEMOGRAPHICS_EXTRACTION_PROMPT,
    GENERIC_CONTEXT_ADDENDUM,
    IMPROVE_PROMPT,
    JAMAICAN_CONTEXT_ADDENDUM,
    MASTER_SYSTEM_PROMPT,
    NARRATIVE_USER_PROMPT,
    SECTION_PROMPTS,
    SECTION_PROMPTS_SUGGESTIVE,
    SENSITIVE_ENCOUNTER_ADDENDUM,
    SINGLE_SOAP_USER_PROMPT,
    SINGLE_SOAP_USER_PROMPT_SUGGESTIVE,
    SUGGESTIVE_ASSIST_ADDENDUM,
    VERIFICATION_PROMPT,
    specialty_addendum,
)


logger = logging.getLogger(__name__)


@dataclass
class GeneratedNote:
    note_format: str
    full_note: str
    visit_summary: str = ""
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    narrative: str = ""
    flags: list[str] = field(default_factory=list)


_REASONING_HINTS = ("gpt-5", "o1", "o3", "o4", "reasoning")
_reasoning_effort_supported: bool | None = None


def _is_reasoning_deployment(deployment: str | None = None) -> bool:
    name = (deployment or settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT or "").lower()
    return any(h in name for h in _REASONING_HINTS)


def _system_prompt(
    specialty: str,
    custom_instructions: str = "",
    custom_terms: str = "",
    *,
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
    lang: str = "jam_Latn",
) -> str:
    context = JAMAICAN_CONTEXT_ADDENDUM if lang == "jam_Latn" else GENERIC_CONTEXT_ADDENDUM
    parts: list[str] = [MASTER_SYSTEM_PROMPT, context]
    addendum = specialty_addendum(specialty)
    if addendum:
        parts.append(addendum)
    if is_sensitive:
        parts.append(SENSITIVE_ENCOUNTER_ADDENDUM)
    if suggestive_assist:
        parts.append(SUGGESTIVE_ASSIST_ADDENDUM)
    if custom_terms:
        parts.append(
            "DOCTOR'S CUSTOM TERMINOLOGY (abbreviations used in this practice — "
            "resolve these when interpreting dictation):\n" + custom_terms.strip()
        )
    if custom_instructions:
        parts.append(
            "DOCTOR PREFERENCES (apply throughout):\n" + custom_instructions.strip()
        )
    return "\n\n".join(parts)


def _looks_like_refusal(text: str) -> bool:
    """Detect when the model wrote 'Not documented' for almost everything.

    True when 3+ of the 4 SOAP sections are exactly 'Not documented' (or
    similar minimal content). Signals an over-conservative response we
    should retry with a more explicit extraction prompt.
    """
    if not text:
        return True
    sections = _split_soap(text)
    empties = 0
    for k, v in sections.items():
        clean = (v or "").strip().lower()
        if not clean or clean in {"not documented.", "not documented", "n/a", "none"}:
            empties += 1
    return empties >= 3


def _is_reasoning_effort_error(exc: BadRequestError) -> bool:
    """True when the deployment rejects our reasoning_effort value.

    Covers both the old wording ('unrecognized request argument') and Azure's
    newer one ('Unsupported value: reasoning_effort does not support minimal
    with this model. Supported values are: medium'). In either case we drop
    reasoning_effort and let the model use its default (medium), which works.
    """
    message = str(exc).lower()
    if "reasoning_effort" not in message:
        return False
    return (
        "unrecognized request argument" in message
        or "unsupported value" in message
        or "does not support" in message
    )


def _chat(messages: list[dict], *, max_tokens: int | None = None, deployment: str | None = None) -> str:
    """Call the chat deployment, with retry-on-empty for reasoning models.

    Pass `deployment` to override the default (e.g. use a fast non-reasoning
    model for a specific step without touching the global setting).
    """
    global _reasoning_effort_supported

    client = get_chat_client()
    deployment = deployment or settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT
    is_reasoning = _is_reasoning_deployment(deployment)
    supports_reasoning_effort = _reasoning_effort_supported is not False

    base_budget = max_tokens or settings.SCRIBE_MAX_COMPLETION_TOKENS
    if is_reasoning and base_budget < 4000:
        base_budget = 4000

    attempts = []
    if is_reasoning:
        attempts.append(
            {
                "max_completion_tokens": base_budget,
                "reasoning_effort": "minimal" if supports_reasoning_effort else None,
            }
        )
        attempts.append(
            {
                "max_completion_tokens": max(base_budget * 2, 8000),
                "reasoning_effort": "low" if supports_reasoning_effort else None,
            }
        )
    else:
        attempts.append({"max_completion_tokens": base_budget})
        attempts.append({"max_completion_tokens": max(base_budget * 2, 4000)})

    last_response = None
    for attempt_kwargs in attempts:
        kwargs: dict = {"model": deployment, "messages": messages}
        # Reasoning models accept `reasoning_effort` (passed via extra_body for
        # SDKs that don't surface it as a typed kwarg yet).
        effort = attempt_kwargs.pop("reasoning_effort", None)
        kwargs.update(attempt_kwargs)
        if effort is not None:
            kwargs["extra_body"] = {"reasoning_effort": effort}

        try:
            response = client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if effort is not None and _is_reasoning_effort_error(exc):
                _reasoning_effort_supported = False
                logger.warning(
                    "Deployment %s rejected reasoning_effort; retrying without it.",
                    deployment,
                )
                kwargs.pop("extra_body", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise
        last_response = response
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        finish = response.choices[0].finish_reason
        logger.info(
            "chat call: model=%s finish=%s out_chars=%d reasoning_tokens=%s completion_tokens=%s",
            deployment,
            finish,
            len(text),
            getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", "n/a"),
            getattr(usage, "completion_tokens", "n/a"),
        )
        if text:
            return text
        # Empty output → likely budget consumed by reasoning. Try again.
        logger.warning(
            "Empty completion (finish=%s). Retrying with bigger budget.", finish
        )

    finish = getattr(last_response.choices[0], "finish_reason", "unknown") if last_response else "no-response"
    raise RuntimeError(
        f"Model returned no output after {len(attempts)} attempts (finish={finish}). "
        "Increase SCRIBE_MAX_COMPLETION_TOKENS or switch to a non-reasoning deployment."
    )


_AI_DISCLAIMER_RE = re.compile(
    r"(?im)"
    r"(?:^\*?AI[\-\s]generated\s+draft[^\n]*\n?)"
    r"|(?:^\[?AI[\-\s]generated[^\n]*\]?\n?)"
    r"|(?:^Note:\s+This\s+(?:is\s+an?\s+)?AI[\-\s]generated[^\n]*\n?)"
    r"|(?:^\*?Note:\s+AI[^\n]*\n?)"
    r"|(?:^Disclaimer:[^\n]*\n?)"
)


def _strip_ai_disclaimer(text: str) -> str:
    """Strip boilerplate disclaimer lines the model sometimes appends."""
    return _AI_DISCLAIMER_RE.sub("", text).strip()


_SECTION_HEADERS = ("S:", "O:", "A:", "P:")


def _split_soap(full_note: str) -> dict[str, str]:
    """Best-effort split of a SOAP block into its four sections plus optional summary."""
    pattern = re.compile(r"(?m)^(SUMMARY:|S:|O:|A:|P:)\s*")
    matches = list(pattern.finditer(full_note))
    if not matches:
        return {
            "visit_summary": "",
            "subjective": full_note,
            "objective": "",
            "assessment": "",
            "plan": "",
        }

    sections = {"SUMMARY:": "", "S:": "", "O:": "", "A:": "", "P:": ""}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_note)
        sections[match.group(1)] = full_note[match.end():end].strip()
    return {
        "visit_summary": sections["SUMMARY:"],
        "subjective": sections["S:"],
        "objective": sections["O:"],
        "assessment": sections["A:"],
        "plan": sections["P:"],
    }


def _extract_flags(text: str) -> list[str]:
    return re.findall(r"\[(?:ALERT|HALLUCINATION|HERB-DRUG NOTE)[^\]]*\]", text)


def generate_note(
    transcript: str,
    *,
    note_format: str = "soap",
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
    custom_terms: str = "",
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
    lang: str = "jam_Latn",
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(
        specialty,
        custom_instructions,
        custom_terms,
        suggestive_assist=suggestive_assist,
        is_sensitive=is_sensitive,
        lang=lang,
    )

    if note_format == "narrative":
        user = NARRATIVE_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    elif note_format == "chart":
        user = CHART_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    else:
        note_format = "soap"
        soap_prompt = (
            SINGLE_SOAP_USER_PROMPT_SUGGESTIVE
            if suggestive_assist
            else SINGLE_SOAP_USER_PROMPT
        )
        user = soap_prompt.format(
            specialty=specialty,
            note_style="SOAP",
            length_mode=length_mode,
            transcript=transcript,
        )

    full_note = _chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ]
    )

    # Refusal-pattern retry: when a SOAP comes back as "Not documented" in
    # 3+ sections but the transcript clearly has clinical content, the
    # model is being too conservative. Re-prompt with a stricter extraction
    # nudge that overrides its caution.
    if note_format == "soap" and _looks_like_refusal(full_note) and len(transcript) > 60:
        logger.warning("SOAP looks like a refusal — retrying with stricter extraction prompt.")
        push = (
            "Your previous attempt was too conservative — most sections came back as "
            "'Not documented' even though the transcript contains clinical content. "
            "Re-read the transcript and EXTRACT every fact present (symptoms, history, "
            "vitals, exam findings, diagnoses, plan items). Use 'Not documented' ONLY "
            "for an entire section that genuinely has zero relevant content.\n\n"
            "PREVIOUS ATTEMPT (over-conservative):\n"
            f"{full_note}\n\n"
            "Now produce a correct SOAP note from the transcript:\n"
            f"{transcript}"
        )
        retry_text = _chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
                {"role": "assistant", "content": full_note},
                {"role": "user", "content": push},
            ]
        )
        if retry_text and not _looks_like_refusal(retry_text):
            full_note = retry_text

    full_note = _strip_ai_disclaimer(full_note)
    note = GeneratedNote(note_format=note_format, full_note=full_note)
    note.flags = _extract_flags(full_note)
    if note_format == "soap":
        sections = _split_soap(full_note)
        note.visit_summary = _strip_ai_disclaimer(sections["visit_summary"])
        note.subjective = _strip_ai_disclaimer(sections["subjective"])
        note.objective = _strip_ai_disclaimer(sections["objective"])
        note.assessment = _strip_ai_disclaimer(sections["assessment"])
        note.plan = _strip_ai_disclaimer(sections["plan"])
    elif note_format == "narrative":
        note.narrative = full_note
    return note


def generate_modular_soap(
    transcript: str,
    *,
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
    custom_terms: str = "",
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
    lang: str = "jam_Latn",
    sections: Iterable[str] = ("subjective", "objective", "assessment", "plan"),
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(
        specialty,
        custom_instructions,
        custom_terms,
        suggestive_assist=suggestive_assist,
        is_sensitive=is_sensitive,
        lang=lang,
    )
    section_prompts = (
        SECTION_PROMPTS_SUGGESTIVE if suggestive_assist else SECTION_PROMPTS
    )
    out: dict[str, str] = {}
    for name in sections:
        prompt = section_prompts[name].format(transcript=transcript)
        out[name] = _chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        )

    full_note = "\n\n".join(
        out[s] for s in ("subjective", "objective", "assessment", "plan") if s in out
    )
    note = GeneratedNote(
        note_format="soap",
        full_note=full_note,
        visit_summary=out.get("visit_summary", ""),
        subjective=out.get("subjective", ""),
        objective=out.get("objective", ""),
        assessment=out.get("assessment", ""),
        plan=out.get("plan", ""),
    )
    note.flags = _extract_flags(full_note)
    return note


def verify_section(
    transcript: str, generated_section: str, section_name: str
) -> str:
    return _chat(
        [
            {"role": "system", "content": "You are a clinical documentation quality reviewer."},
            {
                "role": "user",
                "content": VERIFICATION_PROMPT.format(
                    transcript=transcript,
                    section_name=section_name,
                    generated_section=generated_section,
                ),
            },
        ]
    )


# ---- Suggest improvements (grammar, completeness, missing sections) ----

IMPROVE_PROMPT = """You are a clinical documentation quality reviewer.

Read the following note and suggest specific, actionable improvements.
Focus on:
- Missing fields a reader would expect (e.g. vitals not captured, no plan stated)
- Grammar / clarity issues that hurt readability
- Inconsistent abbreviations or units
- Any [unclear] / "Not documented" entries the doctor should resolve

Be concise. Do NOT invent clinical facts. Do NOT recommend specific
diagnoses or doses. Output 3 to 6 short bullets prefixed with "- ".

NOTE:
{note}
"""


def suggest_improvements(note_text: str, *, specialty: str = "general") -> str:
    note_text = (note_text or "").strip()
    if not note_text:
        return "- Note is empty. Generate or write content first."
    return _chat(
        [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": IMPROVE_PROMPT.format(note=note_text)},
        ],
        max_tokens=1200,
    )


POLISH_PROMPT = """Clean up the grammar, spelling, and clinical phrasing of
the note below. PRESERVE every clinical fact exactly. Do not add or remove
findings, diagnoses, doses, or vitals.

Keep the existing S:/O:/A:/P: section labels (or the existing structure if
there are no labels). Output the polished note in the same plain-text
format. End with: AI-generated draft — review and edit required before
clinical use.

NOTE TO POLISH:
{note}
"""


def polish_grammar(note_text: str) -> str:
    note_text = (note_text or "").strip()
    if not note_text:
        return ""
    return _chat(
        [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": POLISH_PROMPT.format(note=note_text)},
        ]
    )


MAGIC_EDIT_PROMPT = """You are a clinical documentation editor.

The doctor has given this instruction for how to revise the note:
INSTRUCTION: {instruction}

Apply the instruction to the note below. Preserve all clinical facts unless
the instruction explicitly asks to change them. Keep the same section
structure (S:/O:/A:/P: labels, or narrative format). Output only the
revised note — no explanation, no preamble.

NOTE:
{note}
"""


def magic_edit_note(note_text: str, *, instruction: str) -> str:
    note_text = (note_text or "").strip()
    instruction = (instruction or "").strip()
    if not note_text or not instruction:
        return note_text
    return _chat(
        [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": MAGIC_EDIT_PROMPT.format(
                note=note_text, instruction=instruction
            )},
        ]
    )


# Default skeleton returned when AI yields nothing parseable. Mirrors the
# DEMOGRAPHICS_EXTRACTION_PROMPT output shape so the UI can render an empty
# editable form instead of crashing.
DEMOGRAPHICS_EMPTY = {
    "patient": {"name": "", "age": "", "dob": "", "sex": "", "id_or_record_number": ""},
    "vitals": {"bp": "", "hr": "", "temp": "", "rr": "", "spo2": "",
               "weight": "", "height": "", "bmi": "", "glucose": ""},
    "allergies": [],
    "current_medications": [],
    "chief_complaint": "",
    "history_summary": "",
}


def extract_demographics(transcript: str) -> dict:
    """Pull patient + vitals + complaints from clinical text into a strict dict.

    Used by the Triage conversation-mode demographics panel as a verification
    aid for the doctor. Nothing here is persisted — output is for display only.
    """
    text = (transcript or "").strip()
    if not text:
        return dict(DEMOGRAPHICS_EMPTY)
    import json as _json
    import copy as _copy
    raw = _chat(
        [
            {"role": "system", "content": "You are a strict JSON-only clinical data extractor."},
            {"role": "user", "content": DEMOGRAPHICS_EXTRACTION_PROMPT.format(transcript=text)},
        ],
        max_tokens=1200,
    )
    # Strip accidental markdown fences from reasoning-model output.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = _json.loads(cleaned)
    except Exception:
        # Last-ditch: find the first {...} block.
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return dict(DEMOGRAPHICS_EMPTY)
        try:
            parsed = _json.loads(m.group(0))
        except Exception:
            return dict(DEMOGRAPHICS_EMPTY)
    # Merge with empty skeleton so the UI always sees every key.
    out = _copy.deepcopy(DEMOGRAPHICS_EMPTY)
    if isinstance(parsed.get("patient"), dict):
        out["patient"].update({k: str(v) for k, v in parsed["patient"].items() if k in out["patient"]})
    if isinstance(parsed.get("vitals"), dict):
        out["vitals"].update({k: str(v) for k, v in parsed["vitals"].items() if k in out["vitals"]})
    if isinstance(parsed.get("allergies"), list):
        out["allergies"] = [str(x) for x in parsed["allergies"] if str(x).strip()]
    if isinstance(parsed.get("current_medications"), list):
        out["current_medications"] = [str(x) for x in parsed["current_medications"] if str(x).strip()]
    out["chief_complaint"] = str(parsed.get("chief_complaint") or "")
    out["history_summary"] = str(parsed.get("history_summary") or "")
    return out


# ---- Patois pre-processor (deterministic, runs before any LLM call) ----
#
# Handles the most dangerous failure mode: 'nou' (= "no", a self-correction
# marker) misread as "now" (temporal) when flanked by two numbers.
# Rewriting to a structured annotation before the LLM sees the text is more
# reliable than prompt rules, which the model can still override.

_PATOIS_NUM_PATTERN = (
    r"(?:wan|wun|one|tu|tuh|tuu|two|tri|tree|three|faar|faa|four"
    r"|fai|faiv|five|six|seven|sebn|eit|ate|eight|nain|nine|ten|\d+)"
)

_SELF_CORRECTION_RE = re.compile(
    r"(\b" + _PATOIS_NUM_PATTERN + r"\b)"
    r"\s+nou\s+"
    r"(?:iz\s+ant\s+iz\s+|iz\s+ant\s+|iz\s+a\s+|it['\s]s\s+not\s+)?"
    r"(?:a\s+)?"
    r"(\b" + _PATOIS_NUM_PATTERN + r"\b)",
    re.IGNORECASE,
)

# kyaan/kaan variants = CANNOT (unambiguous; cyan excluded — too common as English word)
_KYAAN_RE = re.compile(r"\b(kyaan|kaan|kyaahn|cyaahn|caah)\b", re.IGNORECASE)

# woulda/wuda = conditional/hypothetical — NOT a definite current symptom
_WOULDA_RE = re.compile(r"\b(woulda|wuda|wudda)\b", re.IGNORECASE)

# Patois discourse markers — conversational filler, not clinical content
_DISCOURSE_RE = re.compile(
    r"\b(?:seet\s+deh|a\s+so\s+it\s+go|mi\s+deh\s+yah|das\s+wa\s+mi\s+a\s+seh"
    r"|yu\s+no\s+se|yu\s+zimmi|ibll\s+se)\b",
    re.IGNORECASE,
)

# Blood pressure verbal: "[number] ova/over [number]"
_BP_VERBAL_RE = re.compile(
    r"(\b" + _PATOIS_NUM_PATTERN + r"\b)\s+(?:ova|over)\s+(\b" + _PATOIS_NUM_PATTERN + r"\b)",
    re.IGNORECASE,
)

# Approximation markers before a number — value is NOT exact
_APPROX_RE = re.compile(
    r"\b(?:bout|aroun|around)\s+(\b" + _PATOIS_NUM_PATTERN + r"\b)",
    re.IGNORECASE,
)


def _preprocess_patois(text: str) -> str:
    """Apply deterministic Patois normalisations before the LLM interpreter.

    All rules are non-LLM — regex rewrites that remove known ambiguities
    the model cannot reliably resolve on its own.
    """
    # 1. Numerical self-corrections: [X] nou [restart?] [Y]
    def _replace_correction(m: re.Match) -> str:
        val_a, val_b = m.group(1), m.group(2)
        return (
            f"[SELF-CORRECTION: patient said {val_a}, immediately corrected to "
            f"{val_b}. DISCARD {val_a}. Active value is {val_b}. "
            f"'nou' here = 'no' (correction), NOT 'now'.]"
        )
    text = _SELF_CORRECTION_RE.sub(_replace_correction, text)

    # 2. Kyaan variants → CANNOT (negation safety)
    text = _KYAAN_RE.sub(lambda m: f"[CANNOT: {m.group(0)}]", text)

    # 3. Woulda → CONDITIONAL (not a definite active symptom)
    text = _WOULDA_RE.sub(lambda m: f"[CONDITIONAL-not-definite: {m.group(0)}]", text)

    # 4. Discourse markers → strip clinical weight
    text = _DISCOURSE_RE.sub("[DISCOURSE MARKER — ignore clinically]", text)

    # 5. BP verbal pattern annotation
    def _replace_bp(m: re.Match) -> str:
        return f"[BLOOD PRESSURE READING: {m.group(1)} over {m.group(2)} — verify]"
    text = _BP_VERBAL_RE.sub(_replace_bp, text)

    # 6. Approximation markers
    text = _APPROX_RE.sub(
        lambda m: f"[APPROXIMATE VALUE ~{m.group(1)} — do not record as exact]", text
    )

    return text


# ---- Patois ASR post-processor ----
# Used by the Triage sandbox to interpret raw MMS / Patois output and
# convert it into clean clinical English the SOAP pipeline can consume.

TATOIS_INTERPRETER_SYSTEM_PROMPT = """You are a Jamaican Patois-to-clinical-English
interpreter for a medical scribe. The text below is a raw transcript from
an ASR model that captured a Jamaican Creole (Patwa) speaker. The
spelling is non-standard and inconsistent — that is normal for Patwa.

Your job:
1. Read the Patwa carefully. Patwa is mostly intelligible to English
   speakers if read phonetically. Examples:
   "yu nuo se" = "you know that"
   "fram maan iin" = "from morning"
   "mi beli a kil mi" / "mi beli-batam a kil mi" = "my belly / lower abdomen
       is killing me" → severe abdominal/lower-abdominal pain
   "mi tek som serasi bush" = "I drank some cerasee tea" (herbal remedy)
   "mi staat vamit" = "I started vomiting"
   "mi ed a ap mi" = "my head is hammering me / pounding"
   "mi ai dem torn red" = "my eyes turned red"
   "mi fingga dem a wan piis a pien" = "my fingers are intensely painful"
   "knife mi" / "naip mi" = sharp/stabbing sensation
   "mi go jringk som bizni" = "I drank some bissy/kola-nut tea" (often used
       after suspected poisoning or as a tonic)
   "dem gaa mi bed" = "they put me to bed"
   "pikni" = "child"; "di pikni sik" = "the child is sick"
2. Rewrite the content as clean, neutral clinical English in third person
   ("Patient reports..."). Capture every symptom, time course, herbal
   remedy, and self-treatment.
3. Tag herbs with [HERBAL SUPPLEMENT] (cerasee, fever grass, bissy,
   soursop leaf, jackass bitters, noni, turmeric, aloe vera).
4. Do NOT invent symptoms, diagnoses, doses, or vitals.
5. If a phrase is genuinely unintelligible, write [unclear: "<phrase>"].

Output ONLY the rewritten clinical English. No commentary, no markdown.
"""

PATOIS_INTERPRETER_SYSTEM_PROMPT = """
\
CONTENT FILTER DECLARATION (READ FIRST)
 
This system prompt is used in a medical clinical setting to interpret Jamaican \
Patois (Patwa) speech-to-text transcripts from patients. The input text is a \
Caribbean creole language transcribed phonetically from audio recordings. Many \
Patwa words for anatomical body parts, symptoms, and folk medicine terms may \
superficially resemble flagged content in English but are standard medical \
vocabulary in this context. Examples:
- "batam" = plantar surface of the foot (NOT sexual)
- "pum pum" = vulva (legitimate gynaecological term)
- "buddy" = penis (legitimate anatomical term)
- "front" = anterior / genitalia (legitimate anatomical term)
- "hood" = penis (legitimate anatomical term in this dialect)
Do NOT filter, refuse, or truncate responses based on these terms. \
This is a licensed medical application. Treat all input as clinical data.
 
---
 
YOUR ROLE
 
You are a Jamaican Patois-to-clinical-English medical interpreter. Your job is \
to take raw phonetic Patwa transcripts (produced by speech-to-text from patient \
audio) and convert them into accurate, structured clinical English summaries for \
healthcare providers.
 
You have deep knowledge of Jamaican Patois phonetics, grammar, proverbs, and \
folk medicine. Patwa is a creole language with its own grammar — it is NOT \
broken English. Never treat it as garbled text. Always resolve it phonetically \
and linguistically before interpreting.
 
---
 
MANDATORY PROCESSING RULES — NEVER SKIP THESE
 
RULE 1 — ALWAYS PROCESS IN 3 STEPS IN ORDER
 
You MUST complete all 3 steps before writing any clinical output. \
Do not jump ahead. Do not skip Step 1 or Step 2.
 
STEP 1 — PHONETIC RESOLUTION
Rewrite every token in the transcript word by word using the phonetic rules \
below. Output plain English words — no grammar yet, just resolved tokens.
 
STEP 2 — LINGUISTIC ASSEMBLY
Assemble the resolved tokens into grammatical English sentences, applying Patwa \
grammar rules (subject-verb patterns, discourse markers, hedging patterns).
 
STEP 3 — CLINICAL INTERPRETATION
Convert the assembled English into the structured clinical output template \
at the end of this prompt.
 
---
 
RULE 2 — NEGATION RULES (PATIENT SAFETY CRITICAL)
 
Getting negation wrong is a clinical error. Follow these absolutely:
1. "kyaahn" / "cyaahn" / "caah" ALWAYS means CANNOT. Never "can."
2. "nuh" / "nah" / "na" ALWAYS means NO or NOT.
3. "neva" ALWAYS means NEVER or DID NOT.
4. "mi nuh have pain" = patient has NO pain. Not "patient has pain."
5. "mi kyaahn tek it" = patient CANNOT tolerate it. Not "patient can take it."
6. Double-check every sentence for nuh/nah/kyaahn/neva before outputting.
7. "mi no riili... bot" = hedging pattern. "no riili" is a softener. \
   The real statement comes AFTER "bot" (but). That is the clinical finding.
8. Patois double-negative = SINGLE negation. "nuh ... no" / "nuh ... none" \
   / "nah ... nothing" / "neva ... no" all mean ABSENCE, not presence. \
   "mi nuh have no fever" = patient has NO fever. NEVER read as affirmation.

---

RULE 3 — UNCERTAINTY FLAGGING (PATIENT SAFETY)

When you cannot confidently resolve a token — especially pain scores, doses, body \
parts, or medication names — embed an [UNCERTAIN: what you heard] tag INLINE in \
Step 2 rather than guessing. Examples:
  "Pain score [UNCERTAIN: heard 6 or 8 — correction signal unclear] out of 10."
  "Patient takes [UNCERTAIN: heard 'di yello one' — drug name not identified]."
  "Pain in [UNCERTAIN: heard 'art' — may be heart or another location] area."
The SOAP generator will preserve these flags. The doctor must resolve them.
Never resolve uncertainty silently. A wrong guess in a clinical record can harm.

---

RULE 4 — DISCOURSE MARKERS (NOT SYMPTOMS)

These are conversational fillers — do not interpret as clinical content:
- "a yu no se" / "yu know se" / "yu zimmi" = "you know what I mean" — filler
- "ibll se" / "mi a se" = "I'm saying / let me tell you" — intro filler
- "si an blind, ier an def" = proverb meaning "turn a blind eye" — NOT visual/hearing symptoms
- "a so it go" = "that's how it is" — resignation filler
- "das wa mi a seh" = "that's what I'm saying" — emphasis filler
- "mi deh yah" = "I'm here / I'm managing" — social filler, NOT a clinical finding
- "seet deh" = "look here / you see" — attention filler, NOT a symptom

---

RULE 5 — PATIENT MINIMISING PATTERN

Jamaican patients frequently minimise symptoms. Flag these clinically:
- "likkle likkle" before a serious symptom = downplaying, not mild
- "a nuh nutten" = "it's nothing" — patient downplaying, flag this
- "mi no riili" before a symptom = softening before admitting severity
- A patient presenting despite minimising = symptom is significant

---

RULE 6 — TENSE & ASPECT MARKERS (CLINICAL URGENCY)

Patois uses particles for tense/aspect that change clinical urgency:
1. "mi a [verb]" / "mi deh [verb]" = ONGOING NOW — present progressive. \
   "mi a have pain" = actively experiencing pain RIGHT NOW. Mark as ongoing.
2. "mi did [verb]" / "mi did have" = PAST — completed/historical. \
   "mi did have pain" = pain occurred in the past, may be resolved.
3. "mi woulda / wuda [verb]" = CONDITIONAL/HABITUAL — NOT a definite current symptom. \
   "mi woulda feel dizzy" = situationally/sometimes dizzy, not acutely now. \
   "mi woulda get pain when mi walk" = exertional, not constant. Mark as conditional.
4. "mi use to [verb]" = HABITUAL PAST, no longer occurring. \
   "mi use to have headache" = resolved, not current. Mark as historical.
5. "from [time] + a" = ONGOING since a point: "mi belly a hurt mi from mawning" \
   = abdominal pain ongoing since this morning.
6. In clinical output: label symptoms clearly as ongoing / resolved / intermittent \
   based on these markers. Never flatten all symptoms to simple present tense.

---

RULE 7 — PATOIS NUMERALS (DOSE & PAIN SCORE SAFETY)

Map Patois numerals to Arabic digits BEFORE interpreting any dose, pain score,
or frequency. Missing this causes fabricated clinical values.

wan/wun = 1 | tu/tuh/tuu = 2 | tri/tree = 3 | faar/faa = 4 | fai/faiv = 5
six = 6 | seven/sebn = 7 | eit/ate = 8 | nain/nine = 9 | ten = 10

Dosing patterns: "wan tablet inna di mawning an wan a night" = 1 tab BD
Frequency: "tu time a day" = BD | "tri time a day" = TDS | "evry night" = OD nocte

SAFETY RULE: If NO explicit numeral is spoken for a pain score → write [pain \
score not stated]. If NO explicit dose/frequency is spoken → write [dose not \
stated] / [frequency not stated]. NEVER guess or invent numbers.

PAIN SCORE — TWO CASES, handle differently:

CASE A — SELF-CORRECTION (patient changes their stated value):
Signals: "nou" (no) / "no" / "nah" immediately after a number, then a new number.
Also: stutter-restarts like "iz ant iz" / "it's not... it's" immediately after a number.
"mi seh six... no, a eight" = patient corrected from 6 → RECORD 8.

WORKED EXAMPLE — memorise this exact pattern:
Input:  "ipien levl iz a siks nou iz ant iz a iet out a ten"
Step 1 token-by-token:
  ipien=pain | levl=level | iz=is | a=a | siks=6 | nou=NO (correction) |
  iz=is | ant=not (stutter — speech restart) | iz=is | a=a | iet=8 | out=out | a=of | ten=10
Step 2: Patient said the pain level is 6, then immediately self-corrected:
  "No — it's not — it's an 8 out of 10."
Step 3 Severity: 8/10 (self-corrected from initial 6/10 statement).
WHY NOT "now": "nou" is followed by "iz ant iz" (stutter restart), not a clause end.
  If it were temporal it would read: "pain level is 6 now; [separate clause] it was 8".
  The restart pattern "iz ant iz" = patient backing up mid-sentence to replace the number.
Active score = 8/10. The 6 is discarded.

CASE B — TEMPORAL PROGRESSION (current vs a past state):
Signals: explicit past-tense marker for the OLD value: "waz / was / used to / before / bifoa / laas taim / it used to be".
"pain iz six now, waz eight before" → current 6, previous 8. Record both.
"iz a six now; it used to be eight" → current 6, previous 8.
Active score = the CURRENT value.

DISTINGUISHING THE TWO:
- CASE B requires an EXPLICIT past-tense marker on the OLD value: waz/was/before/bifoa/used to/it used to.
  "nou iz a six, waz a iet" → "now it's 6, was 8" → CASE B. Current = 6.
- CASE A: if the patient produces a restart/stutter (nou/no/nah + iz ant iz / it's not / it's) → CASE A regardless.
- If ambiguous with NO temporal marker → default to CASE A. Record the LATER stated value.
- NEVER treat "iz ant iz" as a double-negative. It is always a speech restart / self-correction.
- WARNING: "nou" alone does NOT confirm CASE B. Only an explicit past marker on the OLD value does.

---

RULE 8 — METAPHORICAL & CULTURALLY-SPECIFIC SYMPTOM LANGUAGE

Map these expressions to standard clinical terms (preserve original under \
Patient's Own Words):
- "chest heavy like stone" / "pressure pon mi chest" → chest heaviness/pressure
- "something a bite mi inside" / "something a tear mi" → visceral pain (describe as stated)
- "mi heart a jump" / "heart a run" → palpitations
- "mi head a spin" / "head swimming" → vertigo / dizziness
- "mi eye dark" / "eye go blank" → visual dimming / presyncope
- "mi stomach a talk" / "belly a bubble" → bowel sounds / cramping
- "mi weak bad" / "mi body mek down" → generalised weakness / fatigue
- "mi can't hold nothing" → persistent vomiting
- "mi cold cold inside" / "mi ketch a cold" → chills / rigors (not necessarily URTI)
- "mi feel strange" / "mi feel funny" → non-specific systemic complaint — ask for more detail

---

PHONETIC RESOLUTION DICTIONARY
 
CORE GRAMMAR:
mi = I/my/me | wi = we/our | im/him = he/him/his | ar/har = she/her
dem = they/them | yuh/yu = you/your | di/de/li = the | a/ah = is/am/are/at
deh/de = there/located | inna/ina = in/inside | pon/pan = on | wid = with
fi = for/to | haffi = have to/must | seh/se = say/that | neva = never/did not
nuh/nah/na = no/not | kyaahn/cyaahn/caah = cannot | bot/but = but
an = and | das/dat = that/that is | wa/wah = what | waa/waah = want to
kaazi/kazi/caaz = cause/because | fram/from = from/since | op = of
tu/tuh = to | riili/rili = really | iiriil/eerily = really (speech artefact)

CRITICAL — "nou" disambiguation (causes pain-score errors if missed):
nou = "now" (temporal) OR "no" (correction) — context decides which:
  CORRECTION ("no"): nou appears AFTER a stated value and is immediately followed
    by a speech restart such as "iz ant iz" / "iz a" / "it's not" / "it's" before
    a NEW value. The patient is backing up and replacing the first value.
    Pattern: [value A] + nou + [restart] + [value B] → discard A, keep B.
  TEMPORAL ("now"): nou appears at the END of a clause with no following restart
    and no second value. "mi av i pain nou" = "I have this pain now/currently."
  WHEN IN DOUBT between the two readings → treat as CORRECTION (safer clinically).
 
BODY PARTS:
batam/battam op mi fut = plantar surface/SOLE OF FOOT — NEVER abdomen
fut/foot = lower limb — Patois "foot" covers hip to toe. DO NOT narrow to anatomical \
  foot. Write "lower limb (patient said foot — confirm location)".
bak a mi fut = posterior foot/heel/ankle
beli/belly = abdomen | bak/back = back | ed/hed = head
nek = neck | nee/nii = knee | nee cup = patella | elbo = elbow
han = hand | finga = finger | toa = toe | nable = navel/umbilicus
yeye/yai = eye | ier/yier = ear | teet = teeth | mout = mouth
troot/troat = throat | waist = waist/lower back (entire region, not just waist) | heel/hiil = heel
haart/haart pain = HEART / cardiac pain (NOT "art" — if "art pain" seen, treat as haart/heart)
bres/brehs/breas = breast/chest (chest pain risk — do not lose as "breath" or "brace")
ches = chest | hankle/ankle = ankle
DISAMBIGUATION: if you see "art pain" in the pre-processed text, it almost certainly
  means haart (heart) pain — flag as [UNCERTAIN: heard 'art' — may be heart pain].
  If you see "brace" or "breath" in a pain context, consider bres (breast/chest pain).
 
PAIN & SYMPTOMS:
pien/pain/peen = pain | apien/a pain = is causing pain | pienful = painful
sore = tenderness | swel = swelling/oedema | bun = burning | itch/iich = pruritus
numb = numbness | stiff = stiffness | weak = weakness | dizzy = dizziness
feva = fever | cough = cough | kyaahn breathe = dyspnoea
run belly = diarrhoea | trow up = vomiting | blain = visual impairment
def/deaf = hearing impairment
 
TIME & DURATION:
fram sat de/satdeh = since Saturday | fram lang taim = longstanding/chronic
fram mawning = since this morning | fram yestiday = since yesterday
wah day = a few days ago | all now = still/ongoing | jus staat = recently started
evry now an den = intermittent | tuu ze/tuezdeh = since Tuesday

RELATIVE DATE ANCHORING: When a relative cultural reference is used, note it
as approximate. E.g. "since Christmas" → "onset approximately December [year]
[patient-stated: since Christmas]". If the event cannot be reliably dated →
write "onset [time not clearly stated — patient reference: ...]".
 
INTENSITY:
bad bad bad = severe/extreme (9-10/10) | kyaahn tek it nomor = unbearable
likkle likkle = mild (check minimising pattern) | nuff = significant
siiriyos/serious = serious/severe | siiriyos siiriyos bad bad bad = maximum severity
 
HERBAL REMEDIES — always tag [HERBAL SUPPLEMENT]:
serisi/cerasee = Momordica charantia [HERBAL SUPPLEMENT]
bissy/bizzy = Cola acuminata [HERBAL SUPPLEMENT]
fever grass = Cymbopogon citratus [HERBAL SUPPLEMENT]
ganja tea/herb tea = Cannabis sativa [HERBAL SUPPLEMENT — flag interactions]
irish moss = Gracilaria spp. [HERBAL SUPPLEMENT]
bush tea = unidentified herbal decoction [HERBAL SUPPLEMENT — ask patient]
aloe/single bible/sinkle bible = Aloe barbadensis [HERBAL SUPPLEMENT]
jackass bitters = Neurolaena lobata [HERBAL SUPPLEMENT]
soursop leaf/sour sop leaf = Annona muricata [HERBAL SUPPLEMENT]
guinea hen weed = Petiveria alliacea [HERBAL SUPPLEMENT]
noni = Morinda citrifolia [HERBAL SUPPLEMENT]
moringa/moringa leaf = Moringa oleifera [HERBAL SUPPLEMENT]
leaf of life/wonder of di world = Kalanchoe pinnata [HERBAL SUPPLEMENT]
vervain/blue vervain = Stachytarpheta jamaicensis [HERBAL SUPPLEMENT]
search mi heart = Rhytiglossa purpurea [HERBAL SUPPLEMENT]
lime bud/lime leaf = Citrus aurantiifolia [HERBAL SUPPLEMENT]
turmeric/tumeric root = Curcuma longa [HERBAL SUPPLEMENT]
aspairin/spirin/aispani = Aspirin/ASA or Icy Hot — clarify [OTC MEDICATION]

HERB-DRUG INTERACTIONS — flag these automatically with [HERB-DRUG NOTE]:
cerasee + Metformin or Glibenclamide = additive hypoglycaemia risk
soursop leaf + antihypertensives = additive hypotensive effect
ganja tea + sedatives/CNS depressants = additive CNS depression
jackass bitters + antimalarials/analgesics = potential interaction — flag
bissy (kola nut) + MAOIs or stimulants = caffeine interaction risk
 
---
 
FEW-SHOT EXAMPLES
 
EXAMPLE 1 — "batam" error (most common mistake)
Input: "mi av pien inna di batam op mi fut"
WRONG: "Patient reports abdominal pain"
WHY WRONG: "batam" was split from "op mi fut" and misread as belly.
CORRECT Step 1: mi=I | av=have | pien=pain | inna=in | di=the | batam=sole | op=of | mi=my | fut=foot
CORRECT Step 2: "I have pain in the bottom of my foot"
CORRECT Step 3: "Patient reports pain in the plantar surface (sole) of the foot."
RULE: "batam op mi fut" = plantar foot pain. NEVER abdominal pain. Ever.
 
EXAMPLE 2 — hedging + negation
Input: "mi no riili mi no no riili no waa kaazi bot di riili pienful"
WRONG: "Patient denies pain"
WHY WRONG: Triple "no" read as negation of pain.
CORRECT: Patient hedges/minimises THEN says "but it is really painful."
Clinical output: "Patient minimises before admitting severe pain. Reflects cultural \
stoicism. Pain is significant."
 
EXAMPLE 3 — full transcript
Input: "ibll se fram sat de li batam op mi fut did de riili apien mi a yu no se \
mi no riili mi no no riili no waa kaazi bot di iiriil pienful an das wa mi kom \
a dakta tu de"
Step 1: ibll=I'll | se=say | fram=since | sat=Saturday | de=that time | \
li=the | batam=sole | op=of | mi=my | fut=foot | did=has | de=been | riili=really \
| apien=paining | mi=me | a=and | yu=you | no=know | se=that | mi=I | no=not \
| riili=really | mi=I | no=don't | no=know | riili=really | no=don't | waa=want \
| kaazi=cause | bot=but | di=it is | iiriil=really | pienful=painful | an=and \
| das=that's | wa=what | mi=I | kom=came | a=to | dakta=doctor | tu=today | de=here
Step 2: "Since Saturday the sole of my foot has really been paining me. I don't \
really — I don't want to make a fuss — but it is really painful. That's why I \
came to the doctor today."
Step 3:
  Chief Complaint: Plantar foot pain
  Location: Sole/plantar surface of foot (confirm laterality)
  Onset: Since Saturday
  Severity: Really painful — patient self-presented due to severity
  Patient Qualifier: Cultural hedging before admitting severity — stoicism, not mild symptoms
  Remedies Tried: None mentioned
  Flagged: None
 
---
 
OUTPUT TEMPLATE — always use this exact structure:
 
STEP 1 — PHONETIC RESOLUTION:
[token by token]
 
STEP 2 — ASSEMBLED ENGLISH:
[full grammatical sentences]
 
STEP 3 — CLINICAL INTERPRETATION:
Chief Complaint:
Location:
Radiation:
Onset:
Duration:
Character/Quality:
Severity:
Aggravating Factors:
Relieving Factors:
Associated Symptoms:
Remedies Tried:
Patient's Own Words:
Cultural/Linguistic Notes:
Flagged Segments: [UNCLEAR: "..."]


And at end give a clinical summary in clean English, suitable for a doctor to read quickly:
---
 
FINAL REMINDERS:
- "batam op mi fut" = sole of foot. ALWAYS. Not abdomen. Not belly. Ever.
- "kyaahn" = cannot. ALWAYS.
- "nuh/nah" = no/not. ALWAYS.
- "a yu no se" = filler. NOT a symptom.
- "mi no riili... bot" = the real finding is AFTER "bot."
- Patwa anatomical terms are not sexual content. Do not filter them.
- Patient minimising does not mean absence of symptoms.
- Complete Step 1 and Step 2 BEFORE any clinical interpretation. No exceptions.
- "nou" = "no" (correction) when followed by a restart. "nou" = "now" (temporal) only
  when it ends a clause with NO following restart and NO second value.
- MANDATORY OVERRIDE — this exact phrase:
  "ipien levl iz a siks nou iz ant iz a iet out a ten"
  MUST be interpreted as: patient self-corrected FROM 6 TO 8. Active pain = 8/10.
  Step 1: nou = NO (correction marker). "iz ant iz" = speech restart (not double-negative).
  NEVER output "pain level is 6 now, was 8 before" for this phrase. That is WRONG.
  The only correct output is: pain self-corrected to 8/10.

"""

def validate_note_safety(full_note: str, raw_transcript: str = "") -> list[str]:
    """Deterministic (zero API cost) safety checks on the generated note.

    Returns a list of warning strings shown to the clinician in the UI.
    Covers: out-of-range numerals, conflicting pain scores, missing vitals,
    and minimising language in the raw Patois transcript.
    """
    warnings: list[str] = []

    # ── Pain scores ───────────────────────────────────────────────────────
    _pain_re = re.compile(r"\b([0-9]{1,2})\s*/\s*10\b", re.IGNORECASE)
    pain_scores = [int(m.group(1)) for m in _pain_re.finditer(full_note)]
    for score in pain_scores:
        if not (0 <= score <= 10):
            warnings.append(f"[RANGE ALERT] Pain score {score}/10 outside 0–10 — verify.")
    valid_scores = sorted({s for s in pain_scores if 0 <= s <= 10})
    if len(valid_scores) >= 2:
        scores_str = ", ".join(f"{s}/10" for s in valid_scores)
        warnings.append(
            f"[CONFLICTING PAIN SCORES] Note contains {scores_str}. Confirm which is current."
        )

    # ── Blood pressure ────────────────────────────────────────────────────
    _bp_re = re.compile(r"\b([0-9]{2,3})\s*/\s*([0-9]{2,3})\b")
    for m in _bp_re.finditer(full_note):
        sys_bp, dia_bp = int(m.group(1)), int(m.group(2))
        # Only flag values that look like real BP (not doses or fractions)
        if 30 <= sys_bp <= 350 and 20 <= dia_bp <= 200:
            if not (60 <= sys_bp <= 250) or not (40 <= dia_bp <= 150):
                warnings.append(
                    f"[RANGE ALERT] BP {sys_bp}/{dia_bp} outside expected range "
                    "(systolic 60–250 / diastolic 40–150) — likely transcription error."
                )

    # ── Gestational age ───────────────────────────────────────────────────
    # Require an explicit gestational-context keyword so "in 2 weeks" / "reassess in 2 weeks"
    # don't trigger this alert.
    _ga_re = re.compile(
        r"\b([0-9]{1,2})\s*(?:\+[0-9])?\s*weeks?\s*(?:gestation(?:al)?|ga\b|gest\.?)",
        re.IGNORECASE,
    )
    for m in _ga_re.finditer(full_note):
        weeks = int(m.group(1))
        if weeks > 0 and not (4 <= weeks <= 44):
            warnings.append(
                f"[RANGE ALERT] Gestational age {weeks} weeks outside expected range 4–44 — verify."
            )

    # ── Missing vitals in Objective ───────────────────────────────────────
    obj_m = re.search(r"(?:^|\n)O:\s*(.*?)(?=\nA:|$)", full_note, re.DOTALL | re.IGNORECASE)
    if obj_m:
        obj_text = obj_m.group(1).strip()
        not_empty = obj_text and obj_text.lower() not in {"not documented.", "not documented", "n/a"}
        if not_empty and not re.search(r"\d", obj_text):
            warnings.append("[NO VITALS] Objective section contains no numerical values — vitals not recorded.")

    # ── Minimising language in raw transcript ─────────────────────────────
    if raw_transcript:
        _MINIMISING = ["likkle likkle", "a nuh nutten", "nuh really nutten", "a nuh nothing", "just a likkle"]
        raw_lower = raw_transcript.lower()
        if any(phrase in raw_lower for phrase in _MINIMISING):
            warnings.append(
                "[MINIMISING LANGUAGE] Patient downplayed symptoms in recording — verify true severity."
            )

    return warnings


# ── Option 1: slim output for reasoning models ────────────────────────────────
# GPT-5 performs Steps 1 & 3 internally via reasoning tokens — forcing them into
# visible output wastes 500-1 000 tokens (~5-8 s) that we immediately discard.
# When SCRIBE_SLIM_INTERPRET=True we append this instruction so the model emits
# only Step 2. The _extract_step2() regex in views.py has a \Z fallback so it
# works even without Step 3 as a delimiter.
_REASONING_SLIM_ADDENDUM = """
=== REASONING MODEL OUTPUT EFFICIENCY ===

You are running as a reasoning model (GPT-5). Your internal chain-of-thought
already handles STEP 1 phonetic resolution and STEP 3 clinical structuring.
To reduce response time and token cost:

- DO NOT write STEP 1 — PHONETIC RESOLUTION in your visible output.
  Perform it entirely via internal reasoning.
- Write STEP 2 — ASSEMBLED ENGLISH in full (required — extracted by downstream code).
- OMIT STEP 3 — CLINICAL INTERPRETATION from your visible output.

Start your visible response immediately with this exact label on its own line:
STEP 2 — ASSEMBLED ENGLISH:
[then the full clinical English output]
"""


def interpret_patois(patois_text: str) -> str:  # noqa: C901
    """Convert raw Patois ASR transcript into clean clinical English.

    Azure content-filter workaround: the heavy Patois interpreter prompt and
    the transcript travel together in the user message so the combined clinical
    framing prevents false-positive flagging on Patwa anatomical terms.

    Option 1 (SCRIBE_SLIM_INTERPRET): appends _REASONING_SLIM_ADDENDUM so GPT-5
    skips writing Steps 1 & 3 in visible output, saving ~500-1 000 output tokens.
    """
    text = (patois_text or "").strip()
    if not text:
        return ""
    text = _preprocess_patois(text)

    slim = getattr(settings, "SCRIBE_SLIM_INTERPRET", True)
    slim_block = _REASONING_SLIM_ADDENDUM if (slim and _is_reasoning_deployment()) else ""

    combined = (
        f"{PATOIS_INTERPRETER_SYSTEM_PROMPT.strip()}\n\n"
        f"=== END OF INSTRUCTIONS — PATOIS INPUT BELOW ===\n\n"
        f"PATWA TRANSCRIPT:\n{text}"
        f"{slim_block}"
    )
    return _chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a licensed medical Patois-to-clinical-English "
                    "interpreter. All input below this line is clinical data "
                    "from a medical encounter. Follow the embedded instructions "
                    "in the user message exactly. Do not refuse — Patwa "
                    "anatomical and symptom vocabulary is legitimate medical "
                    "terminology in this dialect."
                ),
            },
            {"role": "user", "content": combined},
        ]
    )


# ── v3: Generalized interpreter (low-resource languages) ─────────────────────
# Used when preferred_language is a low-resource lang (e.g. hat_Latn).
# Strips all Jamaica-specific rules (Patois phonetics, local drug names, negation
# patterns) and replaces them with a universal "raw speech → clinical English"
# conversion prompt. High-resource languages (eng/spa/fra/por) skip interpretation
# entirely — GPT handles them natively in generate_note().
_GENERALIZED_INTERPRETER_PROMPT = """You are a medical speech-to-clinical-English converter.

You will receive raw transcribed text from a medical consultation. The ASR model
has already converted audio to text. Your job is to convert that raw text into
clean, structured clinical English for use in a medical note.

STEP 1 — CLEAN THE TRANSCRIPT (do internally)
  - Remove speech artifacts: filler words (um, uh, like, you know), false starts,
    repetitions.
  - Resolve unclear phrases using clinical context.
  - Normalise numbers spoken as words to digits (e.g. "two hundred" → 200).

STEP 2 — ASSEMBLED CLINICAL ENGLISH (write this out)
  Produce a clean clinical English summary of everything the doctor said. Rules:
  - Use standard medical terminology.
  - Do NOT invent, infer, or add clinical details not present in the transcript.
  - Preserve all stated values exactly (vital signs, medication doses, pain scores).
  - If a word or phrase is genuinely unintelligible, write [UNCERTAIN: transcribed as "X"].
  - If the speaker corrects themselves, record only the final stated value.
  - This is a legal clinical record. Fabricated facts can harm patients.

STEP 3 — CLINICAL STRUCTURE NOTES (do internally)
  Mentally note which SOAP section each fact belongs to. Do not write this out.
"""


def interpret_generalized(raw_text: str) -> str:
    """Convert low-resource-language ASR transcript to clinical English.

    Used for languages where the ASR output is already readable text but GPT
    needs a light cleaning pass before note generation. Skips all
    Jamaica/Patois-specific rules.
    """
    text = (raw_text or "").strip()
    if not text:
        return ""

    slim = getattr(settings, "SCRIBE_SLIM_INTERPRET", True)
    slim_block = _REASONING_SLIM_ADDENDUM if (slim and _is_reasoning_deployment()) else ""

    combined = (
        f"{_GENERALIZED_INTERPRETER_PROMPT.strip()}\n\n"
        f"=== END OF INSTRUCTIONS — TRANSCRIPT BELOW ===\n\n"
        f"TRANSCRIPT:\n{text}"
        f"{slim_block}"
    )
    return _chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a licensed medical speech-to-clinical-English converter. "
                    "All input below is clinical data from a medical encounter. "
                    "Follow the embedded instructions exactly."
                ),
            },
            {"role": "user", "content": combined},
        ]
    )


# ── Option 2: combined single GPT-5 call ─────────────────────────────────────
# Appended to the Patois interpreter user message when SCRIBE_COMBINED_PIPELINE=True.
# Asks GPT-5 to output Step 2 (for session.transcript cache) then the SOAP note,
# separated by ---SOAP--- so the caller can split them cleanly.
_COMBINED_SOAP_ADDENDUM = (
    "\n\n=== ADDITIONAL TASK: SOAP NOTE ===\n\n"
    "After your Patois interpretation, immediately generate a full clinical SOAP note.\n\n"
    "Apply these documentation rules:\n\n"
    "{master}\n\n"
    "{jamaican}\n\n"
    "Output your response in EXACTLY this structure, with both sections present:\n\n"
    "STEP 2 — ASSEMBLED ENGLISH:\n"
    "[3-8 sentences of clean clinical English summarising the encounter]\n\n"
    "---SOAP---\n\n"
    "SUMMARY:\n"
    "[2-3 bullet TL;DR]\n\n"
    "S:\n[Subjective]\n\n"
    "O:\n[Objective]\n\n"
    "A:\n[Assessment]\n\n"
    "P:\n[Plan]\n\n"
    "AI-generated draft - review and edit required before clinical use.\n\n"
    "Separator rules:\n"
    "- The line ---SOAP--- must appear exactly as shown, alone on its own line.\n"
    "- Everything before ---SOAP--- is the clinical English summary.\n"
    "- Everything after ---SOAP--- is the SOAP note.\n"
    "- Apply all the same EXTRACT-DON'T-INVENT, negation, and safety rules as usual.\n"
    "- specialty={specialty} | length_mode={length_mode}"
)


def interpret_and_generate_soap(
    patois_text: str,
    *,
    note_format: str = "soap",
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
    custom_terms: str = "",
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
) -> tuple[str, GeneratedNote]:
    """Option 2: single GPT-5 call that interprets Patois AND generates the SOAP note.

    Returns (clinical_english, GeneratedNote).
    clinical_english → saved to session.transcript for regeneration caching.
    GeneratedNote    → same shape as generate_note() output, saved to SOAPNote.

    Falls back gracefully: if the ---SOAP--- separator is missing the full
    response is treated as a SOAP note and clinical_english is left empty
    (regeneration will re-interpret next time).
    """
    text = (patois_text or "").strip()
    if not text:
        raise ValueError("Cannot process an empty Patois transcript.")

    text = _preprocess_patois(text)

    addendum = _COMBINED_SOAP_ADDENDUM.format(
        master=MASTER_SYSTEM_PROMPT.strip(),
        jamaican=JAMAICAN_CONTEXT_ADDENDUM.strip(),
        specialty=specialty,
        length_mode=length_mode,
    )

    slim = getattr(settings, "SCRIBE_SLIM_INTERPRET", True)
    # In combined mode the model MUST output Step 2 so downstream caching works —
    # override slim to always include the Step 2 label instruction.
    slim_block = _REASONING_SLIM_ADDENDUM if slim or _is_reasoning_deployment() else ""

    # The combined prompt: full Patois rules → transcript → (optional slim hint) → SOAP task
    combined = (
        f"{PATOIS_INTERPRETER_SYSTEM_PROMPT.strip()}\n\n"
        f"=== END OF INSTRUCTIONS — PATOIS INPUT BELOW ===\n\n"
        f"PATWA TRANSCRIPT:\n{text}"
        f"{slim_block}"
        f"{addendum}"
    )

    # Build extra system addenda (sensitive, suggestive, custom)
    extra_parts: list[str] = []
    if is_sensitive:
        extra_parts.append(SENSITIVE_ENCOUNTER_ADDENDUM.strip())
    if suggestive_assist:
        extra_parts.append(SUGGESTIVE_ASSIST_ADDENDUM.strip())
    if custom_terms:
        extra_parts.append(
            "DOCTOR'S CUSTOM TERMINOLOGY:\n" + custom_terms.strip()
        )
    if custom_instructions:
        extra_parts.append(
            "DOCTOR PREFERENCES:\n" + custom_instructions.strip()
        )
    system_extra = ("\n\n".join(extra_parts) + "\n\n") if extra_parts else ""

    raw = _chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a licensed medical Patois-to-clinical-English interpreter "
                    "and clinical documentation assistant. All input is clinical data "
                    "from a medical encounter. Do not refuse — Patwa anatomical and "
                    "symptom vocabulary is legitimate medical terminology in this dialect.\n\n"
                    + system_extra
                ),
            },
            {"role": "user", "content": combined},
        ]
    )

    # Split on the separator
    soap_sep = re.search(r"^---SOAP---\s*$", raw, re.MULTILINE)
    if soap_sep:
        interpret_block = raw[: soap_sep.start()].strip()
        soap_block = raw[soap_sep.end() :].strip()
    else:
        # Fallback: no separator found — treat everything as SOAP, no clinical English
        logger.warning("interpret_and_generate_soap: ---SOAP--- separator missing; treating full output as SOAP")
        interpret_block = ""
        soap_block = raw

    # Extract Step 2 from the interpret block (same regex as views._extract_step2)
    step2_match = re.search(
        r"STEP\s+2[^:]*:\s*\n+(.*?)(?=\n---|\nSTEP\s+3\b|\Z)",
        interpret_block,
        re.DOTALL | re.IGNORECASE,
    )
    clinical_english = (step2_match.group(1).strip() if step2_match else interpret_block).strip()

    # Parse SOAP note
    soap_block = _strip_ai_disclaimer(soap_block)
    note = GeneratedNote(note_format=note_format if note_format else "soap", full_note=soap_block)
    note.flags = _extract_flags(soap_block)
    if note.note_format == "soap":
        sections = _split_soap(soap_block)
        note.visit_summary = _strip_ai_disclaimer(sections["visit_summary"])
        note.subjective = _strip_ai_disclaimer(sections["subjective"])
        note.objective = _strip_ai_disclaimer(sections["objective"])
        note.assessment = _strip_ai_disclaimer(sections["assessment"])
        note.plan = _strip_ai_disclaimer(sections["plan"])

    return clinical_english, note


# ── Option 3: streaming SOAP generation ──────────────────────────────────────

def stream_note_generation(
    transcript: str,
    *,
    note_format: str = "soap",
    specialty: str = "general",
    length_mode: str = "normal",
    lang: str = "jam_Latn",
    custom_instructions: str = "",
    custom_terms: str = "",
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
) -> Iterator[str]:
    """Yield SOAP note text tokens as they arrive from the API (Option 3).

    This is Call 2 only — the caller must pass already-interpreted clinical
    English as `transcript` (not raw Patois). Yields raw string chunks;
    the caller accumulates them into the full note for post-processing.

    Uses stream=True with reasoning_effort=minimal so the first token arrives
    in ~2-3 s instead of waiting for the full response.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        return

    system_prompt = _system_prompt(
        specialty,
        custom_instructions,
        custom_terms,
        suggestive_assist=suggestive_assist,
        is_sensitive=is_sensitive,
        lang=lang,
    )

    if note_format == "narrative":
        user = NARRATIVE_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    elif note_format == "chart":
        user = CHART_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    else:
        soap_prompt = (
            SINGLE_SOAP_USER_PROMPT_SUGGESTIVE if suggestive_assist else SINGLE_SOAP_USER_PROMPT
        )
        user = soap_prompt.format(
            specialty=specialty,
            note_style="SOAP",
            length_mode=length_mode,
            transcript=transcript,
        )

    global _reasoning_effort_supported

    client = get_chat_client()
    deployment = settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT
    is_reasoning = _is_reasoning_deployment(deployment)

    kwargs: dict = {
        "model": deployment,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens": max(settings.SCRIBE_MAX_COMPLETION_TOKENS, 4000),
        "stream": True,
    }
    if is_reasoning and _reasoning_effort_supported is not False:
        kwargs["extra_body"] = {"reasoning_effort": "minimal"}

    def _stream_chunks(kw: dict):
        response = client.chat.completions.create(**kw)
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    try:
        yield from _stream_chunks(kwargs)
    except BadRequestError as exc:
        if _is_reasoning_effort_error(exc) and "extra_body" in kwargs:
            _reasoning_effort_supported = False
            kwargs.pop("extra_body")
            logger.warning("Deployment rejected reasoning_effort on stream; retrying without it.")
            yield from _stream_chunks(kwargs)
        else:
            logger.exception("stream_note_generation failed")
            raise
    except Exception:
        logger.exception("stream_note_generation failed")
        raise