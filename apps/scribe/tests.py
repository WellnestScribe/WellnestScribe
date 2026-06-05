from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from scribe.services.transcription import transcribe_audio


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
