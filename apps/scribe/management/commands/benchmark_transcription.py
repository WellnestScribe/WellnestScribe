"""Compare transcription backends against the same audio file.

Examples:
    python manage.py benchmark_transcription media/scribe_audio/sample.webm
    python manage.py benchmark_transcription sample.wav --backend lightning --repeat 3
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError

from scribe.services.transcription import transcribe_via_lightning, transcribe_via_openai


class Command(BaseCommand):
    help = "Benchmark the OpenAI and/or Lightning transcription backends on one audio file."

    def add_arguments(self, parser):
        parser.add_argument("audio_path", help="Path to the audio file to benchmark.")
        parser.add_argument(
            "--backend",
            default="both",
            choices=["both", "openai", "lightning", "lightning_mms"],
            help="Which backend to benchmark. Default: both.",
        )
        parser.add_argument(
            "--repeat",
            default=1,
            type=int,
            help="How many times to run each backend. Default: 1.",
        )
        parser.add_argument(
            "--language",
            default="en",
            help="Language hint for the OpenAI backend. Default: en.",
        )
        parser.add_argument(
            "--show-transcript",
            action="store_true",
            help="Print the returned transcript after each run.",
        )

    def handle(self, *args, **options):
        audio_path = Path(options["audio_path"]).expanduser().resolve()
        if not audio_path.exists():
            raise CommandError(f"Audio file not found: {audio_path}")

        repeat = max(int(options["repeat"]), 1)
        selected = options["backend"]
        if selected == "both":
            targets = ["openai", "lightning"]
        elif selected == "lightning_mms":
            targets = ["lightning"]
        else:
            targets = [selected]

        for backend in targets:
            self.stdout.write(self.style.NOTICE(f"\nBenchmarking {backend} on {audio_path.name}"))
            durations = []
            last_transcript = ""
            for index in range(repeat):
                started = perf_counter()
                if backend == "openai":
                    transcript = transcribe_via_openai(audio_path, language=options["language"])
                else:
                    transcript = transcribe_via_lightning(audio_path)
                elapsed_ms = int((perf_counter() - started) * 1000)
                durations.append(elapsed_ms)
                last_transcript = (transcript or "").strip()
                self.stdout.write(
                    f"  run {index + 1}: {elapsed_ms} ms · {len(last_transcript)} chars"
                )
                if options["show_transcript"]:
                    self.stdout.write("  transcript:")
                    self.stdout.write(f"  {last_transcript}")

            best_ms = min(durations)
            avg_ms = int(sum(durations) / len(durations))
            self.stdout.write(
                self.style.SUCCESS(
                    f"  summary: best={best_ms} ms · avg={avg_ms} ms · chars={len(last_transcript)}"
                )
            )
