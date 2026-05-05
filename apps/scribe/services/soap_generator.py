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
from typing import Iterable

from django.conf import settings

from .clients import get_chat_client
from .prompts import (
    CHART_USER_PROMPT,
    MASTER_SYSTEM_PROMPT,
    NARRATIVE_USER_PROMPT,
    SECTION_PROMPTS,
    SINGLE_SOAP_USER_PROMPT,
    VERIFICATION_PROMPT,
    specialty_addendum,
)


logger = logging.getLogger(__name__)


@dataclass
class GeneratedNote:
    note_format: str
    full_note: str
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    narrative: str = ""
    flags: list[str] = field(default_factory=list)


_REASONING_HINTS = ("gpt-5", "o1", "o3", "o4", "reasoning")


def _is_reasoning_deployment() -> bool:
    name = (settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT or "").lower()
    return any(h in name for h in _REASONING_HINTS)


def _system_prompt(specialty: str, custom_instructions: str = "") -> str:
    parts: list[str] = [MASTER_SYSTEM_PROMPT]
    addendum = specialty_addendum(specialty)
    if addendum:
        parts.append(addendum)
    if custom_instructions:
        parts.append(
            "DOCTOR-SPECIFIC PREFERENCES (apply throughout):\n"
            + custom_instructions.strip()
        )
    return "\n\n".join(parts)


def _chat(messages: list[dict], *, max_tokens: int | None = None) -> str:
    """Call the chat deployment, with retry-on-empty for reasoning models."""
    client = get_chat_client()
    deployment = settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT
    is_reasoning = _is_reasoning_deployment()

    base_budget = max_tokens or settings.SCRIBE_MAX_COMPLETION_TOKENS
    if is_reasoning and base_budget < 4000:
        base_budget = 4000

    attempts = []
    if is_reasoning:
        attempts.append({"max_completion_tokens": base_budget, "reasoning_effort": "minimal"})
        attempts.append({"max_completion_tokens": max(base_budget * 2, 8000), "reasoning_effort": "low"})
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

        response = client.chat.completions.create(**kwargs)
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


_SECTION_HEADERS = ("S:", "O:", "A:", "P:")


def _split_soap(full_note: str) -> dict[str, str]:
    """Best-effort split of a SOAP block into its four sections."""
    pattern = re.compile(r"(?m)^(S:|O:|A:|P:)\s*")
    matches = list(pattern.finditer(full_note))
    if not matches:
        return {
            "subjective": full_note,
            "objective": "",
            "assessment": "",
            "plan": "",
        }

    sections = {"S:": "", "O:": "", "A:": "", "P:": ""}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_note)
        sections[match.group(1)] = full_note[match.end():end].strip()
    return {
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
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(specialty, custom_instructions)

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
        user = SINGLE_SOAP_USER_PROMPT.format(
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

    note = GeneratedNote(note_format=note_format, full_note=full_note)
    note.flags = _extract_flags(full_note)
    if note_format == "soap":
        sections = _split_soap(full_note)
        note.subjective = sections["subjective"]
        note.objective = sections["objective"]
        note.assessment = sections["assessment"]
        note.plan = sections["plan"]
    elif note_format == "narrative":
        note.narrative = full_note
    return note


def generate_modular_soap(
    transcript: str,
    *,
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
    sections: Iterable[str] = ("subjective", "objective", "assessment", "plan"),
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(specialty, custom_instructions)
    out: dict[str, str] = {}
    for name in sections:
        prompt = SECTION_PROMPTS[name].format(transcript=transcript)
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
