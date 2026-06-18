"""High-level orchestration: audio (or text) → transcript → note.

Uses real AI when SCRIBE_USE_REAL_AI=True and credentials are present,
otherwise falls back to deterministic stubs so the UI still works.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .clients import AIConfigError
from .soap_generator import (
    DEMOGRAPHICS_EMPTY,
    GeneratedNote,
    extract_demographics,
    generate_modular_soap,
    generate_note,
    interpret_and_generate_soap,
    interpret_generalized,
    interpret_patois,
    polish_grammar,
    stream_note_generation,
    suggest_improvements,
)
from .stub import fake_generate_note, fake_transcribe
from .transcription import transcribe_audio

# ── v3: language tier routing ─────────────────────────────────────────────────
# jam_Latn  → Patois interpreter → Jamaica-context SOAP (unchanged)
# hat_Latn  → Generalized interpreter → generic-context SOAP   (low-resource)
# all others → skip interpreter → generic-context SOAP         (high-resource)
_LOW_RESOURCE_LANGS: frozenset[str] = frozenset({"hat_Latn", "wol_Latn", "kin_Latn"})
_JAMAICA_LANGS: frozenset[str] = frozenset({"jam_Latn"})


def _lang_tier(lang: str) -> str:
    """Return 'jamaica' | 'low_resource' | 'high_resource'."""
    if lang in _JAMAICA_LANGS:
        return "jamaica"
    if lang in _LOW_RESOURCE_LANGS:
        return "low_resource"
    return "high_resource"


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
    lang: str = "jam_Latn",
    custom_instructions: str = "",
    custom_terms: str = "",
    suggestive_assist: bool = False,
    is_sensitive: bool = False,
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
                lang=lang,
                custom_instructions=custom_instructions,
                custom_terms=custom_terms,
                suggestive_assist=suggestive_assist,
                is_sensitive=is_sensitive,
            )
        return generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            lang=lang,
            custom_instructions=custom_instructions,
            custom_terms=custom_terms,
            suggestive_assist=suggestive_assist,
            is_sensitive=is_sensitive,
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


def run_magic_edit(note_text: str, instruction: str) -> str:
    if not _use_real_ai():
        return note_text
    try:
        from .soap_generator import magic_edit_note
        return magic_edit_note(note_text, instruction=instruction)
    except AIConfigError as exc:
        logger.warning("Magic edit stub: %s", exc)
        return note_text


def run_interpret_patois(patois_text: str) -> str:
    if not _use_real_ai():
        return patois_text
    try:
        return interpret_patois(patois_text)
    except AIConfigError as exc:
        logger.warning("Interpret patois stub: %s", exc)
        return patois_text


def run_interpret_and_generate_soap(
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
    """Option 2 wrapper: single GPT-5 call for interpret + SOAP generation.

    Returns (clinical_english, GeneratedNote). Falls back to the two-call
    pipeline when real AI is disabled.
    """
    if not _use_real_ai():
        stub = fake_generate_note(
            patois_text,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )
        return patois_text, stub
    try:
        return interpret_and_generate_soap(
            patois_text,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            custom_terms=custom_terms,
            suggestive_assist=suggestive_assist,
            is_sensitive=is_sensitive,
        )
    except AIConfigError as exc:
        logger.warning("Falling back to two-call pipeline: %s", exc)
        clinical_english = interpret_patois(patois_text)
        note = generate_note(
            clinical_english,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            custom_terms=custom_terms,
            suggestive_assist=suggestive_assist,
            is_sensitive=is_sensitive,
        )
        return clinical_english, note


def run_stream_note_generation(
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
):
    """Option 3 wrapper: yields SOAP note tokens as they stream from the API."""
    if not _use_real_ai():
        stub = fake_generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )
        yield stub.full_note
        return
    try:
        yield from stream_note_generation(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            lang=lang,
            custom_instructions=custom_instructions,
            custom_terms=custom_terms,
            suggestive_assist=suggestive_assist,
            is_sensitive=is_sensitive,
        )
    except AIConfigError as exc:
        logger.warning("Stream generation config error: %s", exc)
        stub = fake_generate_note(
            transcript,
            note_format=note_format,
            specialty=specialty,
            length_mode=length_mode,
            custom_instructions=custom_instructions,
            suggestive_assist=suggestive_assist,
        )
        yield stub.full_note


def run_extract_demographics(transcript: str) -> dict:
    """Stub-aware wrapper around extract_demographics().

    In stub mode returns an empty skeleton — the Triage panel is a real-AI
    feature and there's no realistic deterministic demo for free-text vitals.
    """
    if not _use_real_ai():
        return dict(DEMOGRAPHICS_EMPTY)
    try:
        return extract_demographics(transcript)
    except AIConfigError as exc:
        logger.warning("Demographics extract stub: %s", exc)
        return dict(DEMOGRAPHICS_EMPTY)


def run_interpret_generalized(raw_text: str) -> str:
    """v3: low-resource tier — generalized raw-speech → clinical English."""
    if not _use_real_ai():
        return raw_text
    try:
        return interpret_generalized(raw_text)
    except AIConfigError as exc:
        logger.warning("Interpret generalized stub: %s", exc)
        return raw_text


def run_interpret_for_lang(raw_text: str, lang: str = "jam_Latn") -> str:
    """v3: route raw transcript through the correct interpreter tier.

    jamaica      → Patois interpreter (existing pipeline, unchanged)
    low_resource → Generalized interpreter (hat_Latn etc.)
    high_resource → pass-through (eng/spa/fra/por — GPT handles natively)
    """
    tier = _lang_tier(lang)
    if tier == "jamaica":
        return run_interpret_patois(raw_text)
    if tier == "low_resource":
        return run_interpret_generalized(raw_text)
    # high_resource: transcript goes straight to note generation
    return raw_text
