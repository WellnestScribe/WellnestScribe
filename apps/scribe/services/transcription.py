"""Audio transcription via OpenAI gpt-4o(-mini)-transcribe.

NOT Whisper. The gpt-4o-transcribe family accepts the same audio.transcriptions
endpoint shape but runs on the GPT-4o speech model.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .clients import get_transcription_client


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


def transcribe_audio(file_path: str | Path, *, language: str = "en") -> str:
    """Send an audio file to gpt-4o-transcribe and return the transcript text."""
    client = get_transcription_client()
    path = Path(file_path)
    with path.open("rb") as audio:
        response = client.audio.transcriptions.create(
            model=settings.SCRIBE_OPENAI_TRANSCRIBE_MODEL,
            file=audio,
            language=language,
            prompt=MEDICAL_PRIMING_PROMPT,
            response_format="text",
        )
    return response if isinstance(response, str) else getattr(response, "text", "")
