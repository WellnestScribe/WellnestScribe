"""Lazy-initialized OpenAI / Azure OpenAI clients.

We split transcription (OpenAI direct, gpt-4o-transcribe family) from
chat completion (Azure OpenAI deployment) so each can fail independently.
"""

from functools import lru_cache

from django.conf import settings
from openai import AzureOpenAI, OpenAI


class AIConfigError(RuntimeError):
    """Raised when an AI client is requested but credentials are missing."""


@lru_cache(maxsize=1)
def get_transcription_client() -> OpenAI:
    if not settings.SCRIBE_OPENAI_API_KEY:
        raise AIConfigError(
            "SCRIBE_OPENAI_API_KEY not set. Cannot transcribe audio."
        )
    return OpenAI(api_key=settings.SCRIBE_OPENAI_API_KEY)


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
