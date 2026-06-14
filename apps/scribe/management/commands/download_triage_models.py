"""Pre-download Triage models into their respective caches.

Run from a terminal so the doctor doesn't see a multi-GB download stall the UI:
    python manage.py download_triage_models
    python manage.py download_triage_models --omni          # also download omniASR
    python manage.py download_triage_models --skip-mms --skip-t5 --omni

Skips download if the model is already cached. Surfaces a clear error if
the required libraries aren't installed yet.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download Triage ASR and rewrite models (MMS, FLAN-T5, omniASR)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mms",
            default="facebook/mms-1b-l1107",
            help="HuggingFace model id for the Patois ASR model.",
        )
        parser.add_argument(
            "--t5",
            default="google/flan-t5-base",
            help="HuggingFace model id for the rewrite model.",
        )
        parser.add_argument(
            "--omni",
            nargs="?",
            const="omniASR_CTC_1B",
            default=None,
            metavar="MODEL_CARD",
            help="Download omniASR model. Pass alone for omniASR_CTC_1B or supply a card name.",
        )
        parser.add_argument(
            "--skip-mms",
            action="store_true",
            help="Skip downloading the MMS model.",
        )
        parser.add_argument(
            "--skip-t5",
            action="store_true",
            help="Skip downloading the T5 model.",
        )
        parser.add_argument(
            "--lang",
            default="jam",
            help="MMS adapter language code (default: jam).",
        )

    def handle(self, *args, **opts):
        # opts["omni"] is None when --omni was not passed; a string when it was.
        skip_omni = opts["omni"] is None

        if not opts["skip_mms"] or not opts["skip_t5"]:
            try:
                from transformers import (  # type: ignore
                    AutoModelForSeq2SeqLM,
                    AutoProcessor,
                    AutoTokenizer,
                    Wav2Vec2ForCTC,
                )
            except ImportError:
                self.stderr.write(self.style.ERROR(
                    "transformers is not installed. Run:\n"
                    "    pip install transformers accelerate torch torchaudio "
                    "librosa soundfile sentencepiece"
                ))
                return
        else:
            AutoProcessor = AutoModelForSeq2SeqLM = AutoTokenizer = Wav2Vec2ForCTC = None  # noqa: N806

        if not opts["skip_mms"]:
            self.stdout.write(self.style.NOTICE(f"Downloading MMS model: {opts['mms']} (~4 GB)…"))
            try:
                proc = AutoProcessor.from_pretrained(opts["mms"])
                model = Wav2Vec2ForCTC.from_pretrained(opts["mms"])
                proc.tokenizer.set_target_lang(opts["lang"])
                model.load_adapter(opts["lang"])
                self.stdout.write(self.style.SUCCESS(f"MMS ready (lang={opts['lang']})."))
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"MMS download failed: {exc}"))

        if not opts["skip_t5"]:
            self.stdout.write(self.style.NOTICE(f"Downloading T5 model: {opts['t5']} (~990 MB)…"))
            try:
                AutoTokenizer.from_pretrained(opts["t5"])
                AutoModelForSeq2SeqLM.from_pretrained(opts["t5"])
                self.stdout.write(self.style.SUCCESS("FLAN-T5 ready."))
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"T5 download failed: {exc}"))

        if not skip_omni:
            model_card = opts["omni"]
            self.stdout.write(self.style.NOTICE(
                f"Downloading omniASR model: {model_card}\n"
                "First download: ~2 GB via fairseq2 asset store."
            ))
            try:
                from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline  # type: ignore
            except ImportError:
                self.stderr.write(self.style.ERROR(
                    "omnilingual-asr is not installed. Run:\n"
                    "    pip install omnilingual-asr jiwer silero-vad\n"
                    "Also requires libsndfile:\n"
                    "    brew install libsndfile  (macOS)\n"
                    "    apt install libsndfile1  (Linux)"
                ))
                return

            from django.conf import settings as dj_settings
            omni_cache = getattr(dj_settings, "OMNI_CACHE_DIR", "")
            if omni_cache:
                import os
                os.environ.setdefault("FAIRSEQ2_CACHE_DIR", omni_cache)
                self.stdout.write(f"Using FAIRSEQ2_CACHE_DIR={omni_cache}")
            try:
                ASRInferencePipeline(model_card=model_card, device=None)
                from pathlib import Path
                cache_dir = Path.home() / ".cache" / "fairseq2"
                self.stdout.write(self.style.SUCCESS(
                    f"omniASR ({model_card}) ready. Weights at {cache_dir}"
                ))
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"omniASR download failed: {exc}"))
                return

        self.stdout.write(self.style.SUCCESS(
            "Done. Reload the Triage page — the env probe should turn green."
        ))
