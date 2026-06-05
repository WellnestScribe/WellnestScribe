"""Audio transcription backends for WellNest Scribe.

The default path remains the OpenAI / Azure OpenAI speech endpoint, but the
module can also call a remote Lightning AI GPU service that hosts one or more
speech models. The current default remote workflow uses Whisper, while MMS can
still be selected for comparison from the same API.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import requests
from django.conf import settings

from .clients import AIConfigError, get_transcription_client


MEDICAL_PRIMING_PROMPT = (
    "Medical consultation. SOAP note dictation. Jamaican healthcare setting. "
    "Common terms: hypertension, diabetes mellitus, metformin, amlodipine, "
    "enalapril, lisinopril, hydrochlorothiazide, losartan, atenolol, "
    "amoxicillin, augmentin, ciprofloxacin, paracetamol, salbutamol, "
    "omeprazole, atorvastatin, blood pressure, blood sugar, HbA1c, "
    "creatinine, renal function, ECG, chest x-ray. Patois phrases may "
    "appear: 'mi belly a hurt mi', 'mi pressure high', 'mi sugar high', "
    "'di pickney have fever', 'cerasee tea', 'fever grass', 'bissy tea'."
)


def transcribe_via_openai(file_path: str | Path, *, language: str = "en") -> str:
    """Send an audio file to gpt-4o-transcribe and return the transcript text."""

    client = get_transcription_client()
    model_name = settings.SCRIBE_OPENAI_TRANSCRIBE_MODEL
    if settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT:
        model_name = settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT

    path = Path(file_path)
    with path.open("rb") as audio:
        response = client.audio.transcriptions.create(
            model=model_name,
            file=audio,
            language=language,
            prompt=MEDICAL_PRIMING_PROMPT,
            response_format="text",
        )
    return response if isinstance(response, str) else getattr(response, "text", "")


def transcribe_via_lightning(file_path: str | Path) -> str:
    """Send an audio file to the remote Lightning AI transcription API."""

    endpoint = (settings.SCRIBE_LIGHTNING_TRANSCRIBE_URL or "").strip()
    if not endpoint:
        raise AIConfigError(
            "SCRIBE_LIGHTNING_TRANSCRIBE_URL is not set. Point it to the "
            "Lightning AI /transcribe/file endpoint first."
        )

    headers = {}
    token = (settings.SCRIBE_LIGHTNING_TRANSCRIBE_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    path = Path(file_path)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as audio:
        response = requests.post(
            endpoint,
            headers=headers,
            data={
                "backend": settings.SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE,
                "language": settings.SCRIBE_LIGHTNING_TRANSCRIBE_LANGUAGE,
                "target_lang": settings.SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG,
                "device": settings.SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE,
                "model_id": settings.SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID,
                "task": settings.SCRIBE_LIGHTNING_TRANSCRIBE_TASK,
                "compute_type": settings.SCRIBE_LIGHTNING_TRANSCRIBE_COMPUTE_TYPE,
                "beam_size": str(settings.SCRIBE_LIGHTNING_TRANSCRIBE_BEAM_SIZE),
                "chunk_seconds": str(settings.SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS),
            },
            files={"file": (path.name, audio, content_type)},
            timeout=settings.SCRIBE_LIGHTNING_TRANSCRIBE_TIMEOUT,
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        message = response.text[:500] if response.text else str(exc)
        raise RuntimeError(f"Lightning transcription request failed: {message}") from exc

    payload = response.json()
    transcript = (payload.get("transcript") or "").strip()
    if not transcript:
        raise RuntimeError("Lightning transcription service returned an empty transcript.")
    return transcript


def transcribe_audio(file_path: str | Path, *, language: str = "en") -> str:
    """Run the configured transcription backend and return plain text."""

    backend = (settings.SCRIBE_TRANSCRIPTION_BACKEND or "openai").strip().lower()
    if backend in {"lightning", "lightning_mms"}:
        return transcribe_via_lightning(file_path)
    return transcribe_via_openai(file_path, language=language)
