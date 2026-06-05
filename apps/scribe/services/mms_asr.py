"""Reusable MMS ASR helper for local triage and remote GPU experiments.

This module stays free of Django settings so it can be imported from the main
app, a standalone benchmark script, or a Lightning AI Studio microservice.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


class MMSDependencyError(RuntimeError):
    """Raised when MMS ASR dependencies are missing or the runtime is invalid."""


@dataclass
class MMSTranscriptionResult:
    text: str
    model_id: str
    device: str
    target_lang: str
    audio_seconds: float
    chunk_count: int
    preprocessing_ms: int
    inference_ms: int
    total_ms: int
    sample_rate: int = 16_000

    @property
    def realtime_factor(self) -> float | None:
        total_seconds = self.total_ms / 1000 if self.total_ms else 0
        if total_seconds <= 0:
            return None
        return self.audio_seconds / total_seconds


_MMS_CACHE: dict[str, Any] = {}


def probe_mms_runtime() -> dict[str, Any]:
    """Return a lightweight capability report for the current Python runtime."""
    info: dict[str, Any] = {
        "torch": False,
        "torch_version": None,
        "transformers": False,
        "transformers_version": None,
        "cuda": False,
        "cuda_device": None,
        "librosa": False,
        "av": False,
        "numpy": False,
        "model_cached_mms": False,
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
        import transformers  # type: ignore

        info["transformers"] = True
        info["transformers_version"] = transformers.__version__
    except Exception:  # noqa: BLE001
        pass

    try:
        import librosa  # noqa: F401  # type: ignore

        info["librosa"] = True
    except Exception:  # noqa: BLE001
        pass

    try:
        import av  # noqa: F401  # type: ignore

        info["av"] = True
    except Exception:  # noqa: BLE001
        pass

    try:
        import numpy  # noqa: F401  # type: ignore

        info["numpy"] = True
    except Exception:  # noqa: BLE001
        pass

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.exists():
        info["model_cached_mms"] = any(p.name.startswith("models--facebook--mms") for p in cache.iterdir())
    return info


def choose_device(requested: str = "auto") -> str:
    """Resolve `auto` to `cuda` when possible, otherwise `cpu`."""
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise MMSDependencyError(f"Unsupported device '{requested}'. Use auto, cpu, or cuda.")

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError(
            "PyTorch is not installed. Install the Lightning API requirements first."
        ) from exc

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"

    if requested == "cuda" and not torch.cuda.is_available():
        raise MMSDependencyError(
            "CUDA was requested but no CUDA-capable GPU is visible to PyTorch."
        )
    return requested


def _load_mms(*, device: str, target_lang: str, model_id: str):
    cache_key = f"{device}|{target_lang}|{model_id}"
    if cache_key in _MMS_CACHE:
        return _MMS_CACHE[cache_key]

    try:
        from transformers import AutoProcessor, Wav2Vec2ForCTC  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError(
            "transformers is not installed. Run pip install -r deploy/lightning_mms_api/requirements.txt."
        ) from exc

    runtime_device = choose_device(device)
    processor = AutoProcessor.from_pretrained(model_id)
    model = Wav2Vec2ForCTC.from_pretrained(model_id)
    processor.tokenizer.set_target_lang(target_lang)
    model.load_adapter(target_lang)
    model = model.to(runtime_device)
    model.eval()
    _MMS_CACHE[cache_key] = (processor, model, runtime_device)
    return _MMS_CACHE[cache_key]


def _read_audio(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        import av  # type: ignore
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError(
            "Missing audio dependencies. Install av, librosa, and numpy in the runtime."
        ) from exc

    container = av.open(str(audio_path))
    if not container.streams.audio:
        raise MMSDependencyError(f"No audio stream found in {audio_path}.")

    source_rate = container.streams.audio[0].sample_rate or sample_rate
    samples = []
    for frame in container.decode(audio=0):
        arr = frame.to_ndarray()
        if arr.ndim > 1:
            arr = arr.mean(axis=0)
        samples.append(arr)
    if not samples:
        raise MMSDependencyError(f"Unable to decode audio frames from {audio_path}.")

    audio = np.concatenate(samples).astype(np.float32)
    if source_rate != sample_rate:
        audio = librosa.resample(audio, orig_sr=source_rate, target_sr=sample_rate)
    audio_seconds = float(len(audio) / sample_rate)
    return audio, audio_seconds


def transcribe_mms_file(
    audio_path: str | Path,
    *,
    device: str = "auto",
    target_lang: str = "jam",
    model_id: str = "facebook/mms-1b-l1107",
    chunk_seconds: int = 25,
    sample_rate: int = 16_000,
) -> MMSTranscriptionResult:
    """Run MMS on an audio file and return the transcript plus timing metadata."""

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError(
            "PyTorch is not installed. Run pip install -r deploy/lightning_mms_api/requirements.txt."
        ) from exc

    started = perf_counter()
    processor, model, runtime_device = _load_mms(
        device=device,
        target_lang=target_lang,
        model_id=model_id,
    )

    preprocess_started = perf_counter()
    audio, audio_seconds = _read_audio(audio_path, sample_rate=sample_rate)
    chunk_size = max(int(chunk_seconds), 1) * sample_rate
    chunks = [
        audio[index : index + chunk_size]
        for index in range(0, len(audio), chunk_size)
    ] or [audio]
    preprocessing_ms = int((perf_counter() - preprocess_started) * 1000)

    inference_started = perf_counter()
    decoded_chunks: list[str] = []
    for chunk in chunks:
        inputs = processor(chunk, sampling_rate=sample_rate, return_tensors="pt")
        input_values = inputs.input_values.to(runtime_device)
        with torch.no_grad():
            logits = model(input_values).logits
        ids = torch.argmax(logits, dim=-1)
        decoded_chunks.append(processor.batch_decode(ids)[0])
    inference_ms = int((perf_counter() - inference_started) * 1000)
    total_ms = int((perf_counter() - started) * 1000)

    return MMSTranscriptionResult(
        text=" ".join(decoded_chunks).strip(),
        model_id=model_id,
        device=runtime_device,
        target_lang=target_lang,
        audio_seconds=round(audio_seconds, 3),
        chunk_count=len(chunks),
        preprocessing_ms=preprocessing_ms,
        inference_ms=inference_ms,
        total_ms=total_ms,
        sample_rate=sample_rate,
    )
