"""High-level orchestration: audio (or text) → transcript → note.

Uses real AI when SCRIBE_USE_REAL_AI=True and credentials are present,
otherwise falls back to deterministic stubs so the UI still works.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .clients import AIConfigError
from .soap_generator import (
    GeneratedNote,
    generate_modular_soap,
    generate_note,
    interpret_patois,
    polish_grammar,
    suggest_improvements,
)
from .stub import fake_generate_note, fake_transcribe
from .transcription import transcribe_audio


logger = logging.getLogger(__name__)


def _use_real_ai() -> bool:
    return bool(settings.SCRIBE_USE_REAL_AI)


def run_transcription(file_path: str) -> str:
    if not _use_real_ai():
        return fake_transcribe(file_path)
    try:
        return transcribe_audio(file_path).strip()
    except AIConfigError as exc:
        logger.warning("Falling back to stub transcription: %s", exc)
        return fake_transcribe(file_path)


def run_note_generation(
    transcript: str,
    *,
    note_format: str,
    specialty: str,
    length_mode: str,
    custom_instructions: str = "",
    suggestive_assist: bool = False,
) -> GeneratedNote:
    if not _use_real_ai():
        return fake_generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )
    try:
        if (
            note_format == "soap"
            and settings.SCRIBE_PIPELINE_MODE == "modular"
        ):
            return generate_modular_soap(
                transcript,
                specialty=specialty,
                length_mode=length_mode,
                custom_instructions=custom_instructions,
                suggestive_assist=suggestive_assist,
            )
        return generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )
    except AIConfigError as exc:
        logger.warning("Falling back to stub note generation: %s", exc)
        return fake_generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )


def run_suggest_improvements(note_text: str, *, specialty: str = "general") -> str:
    if not _use_real_ai():
        return (
            "- Add chief complaint in plain words.\n"
            "- Document vitals if any were taken.\n"
            "- State whether medication was changed and why.\n"
            "- Add follow-up interval."
        )
    try:
        return suggest_improvements(note_text, specialty=specialty)
    except AIConfigError as exc:
        logger.warning("Improvements stub: %s", exc)
        return "- AI not configured. Add SCRIBE_AZURE_OPENAI_KEY to .env."


def run_polish_grammar(note_text: str) -> str:
    if not _use_real_ai():
        return note_text  # No-op in stub mode.
    try:
        return polish_grammar(note_text)
    except AIConfigError as exc:
        logger.warning("Polish stub: %s", exc)
        return note_text


def run_interpret_patois(patois_text: str) -> str:
    if not _use_real_ai():
        return patois_text
    try:
        return interpret_patois(patois_text)
    except AIConfigError as exc:
        logger.warning("Interpret patois stub: %s", exc)
        return patois_text
