"""Standalone faster-whisper helper for the Lightning speech API bundle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


class WhisperDependencyError(RuntimeError):
    """Raised when Whisper ASR dependencies are missing or invalid."""


@dataclass
class WhisperTranscriptionResult:
    text: str
    model_id: str
    device: str
    compute_type: str
    language: str | None
    task: str
    audio_seconds: float
    segment_count: int
    preprocessing_ms: int
    inference_ms: int
    total_ms: int

    @property
    def realtime_factor(self) -> float | None:
        total_seconds = self.total_ms / 1000 if self.total_ms else 0
        if total_seconds <= 0:
            return None
        return self.audio_seconds / total_seconds


_WHISPER_CACHE: dict[str, Any] = {}


def probe_whisper_runtime() -> dict[str, Any]:
    info: dict[str, Any] = {
        "torch": False,
        "torch_version": None,
        "faster_whisper": False,
        "faster_whisper_version": None,
        "ctranslate2": False,
        "ctranslate2_version": None,
        "cuda": False,
        "cuda_device": None,
        "av": False,
        "numpy": False,
        "model_cached_whisper": False,
    }
    try:
        import torch  # type: ignore

        info["torch"] = True
        info["torch_version"] = torch.__version__
        if torch.cuda.is_available():
            info["cuda"] = True
            info["cuda_device"] = torch.cuda.get_device_name(0)
    except Exception:  # noqa: BLE001
        pass

    try:
        import faster_whisper  # type: ignore

        info["faster_whisper"] = True
        info["faster_whisper_version"] = getattr(faster_whisper, "__version__", None)
    except Exception:  # noqa: BLE001
        pass

    try:
        import ctranslate2  # type: ignore

        info["ctranslate2"] = True
        info["ctranslate2_version"] = getattr(ctranslate2, "__version__", None)
    except Exception:  # noqa: BLE001
        pass

    for module_name, key in (
        ("av", "av"),
        ("numpy", "numpy"),
    ):
        try:
            __import__(module_name)
            info[key] = True
        except Exception:  # noqa: BLE001
            pass

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.exists():
        info["model_cached_whisper"] = any("whisper" in p.name for p in cache.iterdir())
    return info


def choose_whisper_device(requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise WhisperDependencyError(
            f"Unsupported device '{requested}'. Use auto, cpu, or cuda."
        )

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise WhisperDependencyError("PyTorch is not installed.") from exc

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise WhisperDependencyError(
            "CUDA was requested but no CUDA-capable GPU is visible to PyTorch."
        )
    return requested


def choose_compute_type(requested: str, *, device: str) -> str:
    requested = (requested or "auto").strip().lower()
    if requested == "auto":
        return "float16" if device == "cuda" else "int8"
    return requested


def load_whisper_model(
    *,
    device: str,
    model_id: str,
    compute_type: str = "auto",
):
    runtime_device = choose_whisper_device(device)
    runtime_compute_type = choose_compute_type(compute_type, device=runtime_device)
    cache_key = f"{runtime_device}|{runtime_compute_type}|{model_id}"
    if cache_key in _WHISPER_CACHE:
        return _WHISPER_CACHE[cache_key]

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise WhisperDependencyError("faster-whisper is not installed.") from exc

    model = WhisperModel(
        model_size_or_path=model_id,
        device=runtime_device,
        compute_type=runtime_compute_type,
    )
    _WHISPER_CACHE[cache_key] = (model, runtime_device, runtime_compute_type)
    return _WHISPER_CACHE[cache_key]


def _audio_duration_seconds(audio_path: str | Path) -> float:
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise WhisperDependencyError("PyAV is required to inspect audio duration.") from exc

    container = av.open(str(audio_path))
    if not container.streams.audio:
        raise WhisperDependencyError(f"No audio stream found in {audio_path}.")

    stream = container.streams.audio[0]
    duration = float(stream.duration * stream.time_base) if stream.duration else 0.0
    if duration > 0:
        return duration

    sample_rate = stream.sample_rate or 16_000
    samples = 0
    for frame in container.decode(audio=0):
        samples += frame.samples
    return float(samples / sample_rate)


def transcribe_whisper_file(
    audio_path: str | Path,
    *,
    device: str = "auto",
    model_id: str = "large-v3",
    language: str | None = "en",
    task: str = "transcribe",
    compute_type: str = "auto",
    beam_size: int = 5,
    vad_filter: bool = False,
    initial_prompt: str | None = None,
) -> WhisperTranscriptionResult:
    started = perf_counter()
    model, runtime_device, runtime_compute_type = load_whisper_model(
        device=device,
        model_id=model_id,
        compute_type=compute_type,
    )

    preprocess_started = perf_counter()
    audio_seconds = round(_audio_duration_seconds(audio_path), 3)
    preprocessing_ms = int((perf_counter() - preprocess_started) * 1000)

    inference_started = perf_counter()
    segments, info = model.transcribe(
        str(audio_path),
        language=(language or None),
        task=task,
        beam_size=max(int(beam_size), 1),
        vad_filter=vad_filter,
        initial_prompt=initial_prompt or None,
    )
    collected: list[str] = []
    segment_count = 0
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            collected.append(text)
        segment_count += 1
    inference_ms = int((perf_counter() - inference_started) * 1000)
    total_ms = int((perf_counter() - started) * 1000)

    if getattr(info, "duration", None):
        audio_seconds = round(float(info.duration), 3)

    return WhisperTranscriptionResult(
        text=" ".join(collected).strip(),
        model_id=model_id,
        device=runtime_device,
        compute_type=runtime_compute_type,
        language=language or None,
        task=task,
        audio_seconds=audio_seconds,
        segment_count=segment_count,
        preprocessing_ms=preprocessing_ms,
        inference_ms=inference_ms,
        total_ms=total_ms,
    )
