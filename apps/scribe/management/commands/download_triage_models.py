"""Pre-download Triage models (MMS + FLAN-T5) into the HuggingFace cache.

Run from a terminal so the doctor doesn't see a 4 GB download stall the UI:
    python manage.py download_triage_models

Skips download if the model is already cached. Surfaces a clear error if
transformers / torch aren't installed yet.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download the Triage Patois ASR (MMS) and rewrite (FLAN-T5) models."

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

        self.stdout.write(self.style.SUCCESS("Done. Reload the Triage page — the env probe should turn green."))
