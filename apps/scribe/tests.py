from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from scribe.services.transcription import (
    _lightning_request_payload,
    _resolve_lightning_endpoint,
    transcribe_audio,
)


class TranscriptionBackendTests(SimpleTestCase):
    @override_settings(SCRIBE_TRANSCRIPTION_BACKEND="openai")
    @patch("scribe.services.transcription.transcribe_via_openai")
    def test_transcribe_audio_uses_selected_backend(self, mock_openai):
        mock_openai.return_value = "openai transcript"
        text = transcribe_audio("sample.wav", language="en")
        self.assertEqual(text, "openai transcript")
        mock_openai.assert_called_once_with("sample.wav", language="en")

    @override_settings(SCRIBE_TRANSCRIPTION_BACKEND="lightning_mms")
    @patch("scribe.services.transcription.transcribe_via_lightning")
    def test_transcribe_audio_routes_to_lightning_backend(self, mock_lightning):
        mock_lightning.return_value = "lightning transcript"
        text = transcribe_audio("sample.wav")
        self.assertEqual(text, "lightning transcript")
        mock_lightning.assert_called_once_with("sample.wav")

    @override_settings(SCRIBE_TRANSCRIPTION_BACKEND="lightning")
    @patch("scribe.services.transcription.transcribe_via_lightning")
    def test_transcribe_audio_routes_to_lightning_alias(self, mock_lightning):
        mock_lightning.return_value = "lightning transcript"
        text = transcribe_audio("sample.wav")
        self.assertEqual(text, "lightning transcript")
        mock_lightning.assert_called_once_with("sample.wav")

    @override_settings(
        SCRIBE_LIGHTNING_TRANSCRIBE_URL="https://example.com/transcribe/file",
        SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE="mms",
    )
    def test_resolve_lightning_endpoint_prefers_direct_mms_route(self):
        self.assertEqual(
            _resolve_lightning_endpoint(),
            "https://example.com/transcribe/mms/file",
        )

    @override_settings(
        SCRIBE_LIGHTNING_TRANSCRIBE_URL="https://example.com/transcribe/file",
        SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE="whisper",
    )
    def test_resolve_lightning_endpoint_prefers_direct_whisper_route(self):
        self.assertEqual(
            _resolve_lightning_endpoint(),
            "https://example.com/transcribe/whisper/file",
        )

    @override_settings(
        SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE="mms",
        SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE="auto",
        SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID="facebook/mms-1b-l1107",
        SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG="jam",
        SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS=35,
        SCRIBE_LIGHTNING_TRANSCRIBE_MMS_BATCH_SIZE=6,
    )
    def test_lightning_request_payload_for_mms(self):
        self.assertEqual(
            _lightning_request_payload(),
            {
                "device": "auto",
                "model_id": "facebook/mms-1b-l1107",
                "target_lang": "jam",
                "chunk_seconds": "35",
                "batch_size": "6",
            },
        )
