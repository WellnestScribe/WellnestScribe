"""Simple local client for testing the Lightning speech API from your laptop."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the Lightning speech API from a local machine.")
    parser.add_argument("--url", required=True, help="Full transcription endpoint URL.")
    parser.add_argument("--file", required=True, help="Audio file to upload.")
    parser.add_argument("--token", default="", help="Optional bearer token.")
    parser.add_argument("--backend", default="whisper", choices=["whisper", "mms"], help="Which model family to use.")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"], help="Requested device.")
    parser.add_argument("--model-id", default="", help="Override model id.")
    parser.add_argument("--language", default="en", help="Whisper language hint.")
    parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"], help="Whisper task.")
    parser.add_argument("--compute-type", default="auto", help="Whisper compute type.")
    parser.add_argument("--beam-size", type=int, default=5, help="Whisper beam size.")
    parser.add_argument("--target-lang", default="jam", help="MMS adapter language code.")
    parser.add_argument("--chunk-seconds", type=int, default=25, help="MMS chunk size in seconds.")
    args = parser.parse_args()

    audio_path = Path(args.file).expanduser().resolve()
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    payload = {
        "backend": args.backend,
        "device": args.device,
        "language": args.language,
        "task": args.task,
        "compute_type": args.compute_type,
        "beam_size": str(args.beam_size),
        "target_lang": args.target_lang,
        "chunk_seconds": str(args.chunk_seconds),
    }
    if args.model_id:
        payload["model_id"] = args.model_id

    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    with audio_path.open("rb") as audio:
        response = requests.post(
            args.url,
            headers=headers,
            data=payload,
            files={"file": (audio_path.name, audio, content_type)},
            timeout=900,
        )

    response.raise_for_status()
    payload = response.json()
    print("ok:", payload.get("ok"))
    print("backend:", payload.get("backend"))
    print("device:", payload.get("device"))
    print("model_id:", payload.get("model_id"))
    print("total_ms:", payload.get("total_ms"))
    print("realtime_factor:", payload.get("realtime_factor"))
    print("transcript:")
    print(payload.get("transcript", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
