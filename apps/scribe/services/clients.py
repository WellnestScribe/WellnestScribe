"""Lazy-initialized OpenAI / Azure OpenAI clients."""

from functools import lru_cache

from django.conf import settings
from openai import AzureOpenAI, OpenAI


class AIConfigError(RuntimeError):
    """Raised when an AI client is requested but credentials are missing."""


@lru_cache(maxsize=1)
def get_transcription_client() -> AzureOpenAI | OpenAI:
    if (
        settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_KEY
        and settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT
        and settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT
    ):
        return AzureOpenAI(
            api_key=settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_KEY,
            azure_endpoint=settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_ENDPOINT,
            api_version=settings.SCRIBE_AZURE_OPENAI_TRANSCRIBE_API_VERSION,
        )

    if settings.SCRIBE_OPENAI_API_KEY:
        return OpenAI(api_key=settings.SCRIBE_OPENAI_API_KEY)

    raise AIConfigError(
        "No transcription provider configured. Set Azure transcription vars "
        "or SCRIBE_OPENAI_API_KEY."
    )


@lru_cache(maxsize=1)
def get_chat_client() -> AzureOpenAI:
    if not (
        settings.SCRIBE_AZURE_OPENAI_KEY and settings.SCRIBE_AZURE_OPENAI_ENDPOINT
    ):
        raise AIConfigError(
            "SCRIBE_AZURE_OPENAI_KEY / SCRIBE_AZURE_OPENAI_ENDPOINT not set. "
            "Cannot generate notes."
        )
    return AzureOpenAI(
        api_key=settings.SCRIBE_AZURE_OPENAI_KEY,
        azure_endpoint=settings.SCRIBE_AZURE_OPENAI_ENDPOINT,
        api_version=settings.SCRIBE_AZURE_OPENAI_API_VERSION,
    )
