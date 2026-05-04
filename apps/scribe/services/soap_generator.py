"""SOAP / narrative / chart note generation via Azure OpenAI."""

from __future__ import annotations

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
    client = get_chat_client()
    response = client.chat.completions.create(
        model=settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        max_completion_tokens=max_tokens or settings.SCRIBE_MAX_COMPLETION_TOKENS,
    )
    return (response.choices[0].message.content or "").strip()


_SECTION_HEADERS = ("S:", "O:", "A:", "P:")


def _split_soap(full_note: str) -> dict[str, str]:
    """Best-effort split of a SOAP block into its four sections."""
    pattern = re.compile(r"(?m)^(S:|O:|A:|P:)\s*")
    matches = list(pattern.finditer(full_note))
    if not matches:
        return {"subjective": full_note, "objective": "", "assessment": "", "plan": ""}

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
    """Generate a note in the requested format. Single-call pipeline."""
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
    """Modular SOAP: one LLM call per section. Used when SCRIBE_PIPELINE_MODE=modular."""
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

    full_note = "\n\n".join(out[s] for s in ("subjective", "objective", "assessment", "plan") if s in out)
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
    """Return either VERIFIED message or a corrected section."""
    return _chat(
        [
            {
                "role": "system",
                "content": "You are a clinical documentation quality reviewer.",
            },
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
