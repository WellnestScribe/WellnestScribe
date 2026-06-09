"""Standalone MMS ASR helper for the Lightning speech API bundle."""

from __future__ import annotations

import shutil
import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


class MMSDependencyError(RuntimeError):
    """Raised when MMS ASR dependencies are missing or invalid."""


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


def _huggingface_cache_dir() -> Path:
    hf_home = os.getenv("HF_HOME", "").strip()
    if hf_home:
        return Path(hf_home) / "hub"
    transformers_cache = os.getenv("TRANSFORMERS_CACHE", "").strip()
    if transformers_cache:
        return Path(transformers_cache)
    return Path.home() / ".cache" / "huggingface" / "hub"


def probe_mms_runtime() -> dict[str, Any]:
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
        "ffmpeg": False,
        "model_cached_mms": False,
        "model_loaded_mms": False,
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

    for module_name, key in (
        ("librosa", "librosa"),
        ("av", "av"),
        ("numpy", "numpy"),
    ):
        try:
            __import__(module_name)
            info[key] = True
        except Exception:  # noqa: BLE001
            pass

    info["ffmpeg"] = shutil.which("ffmpeg") is not None

    cache = _huggingface_cache_dir()
    if cache.exists():
        info["model_cached_mms"] = any(
            p.name.startswith("models--facebook--mms")
            for p in cache.iterdir()
        )
    info["model_loaded_mms"] = bool(_MMS_CACHE)
    return info


def choose_mms_device(requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise MMSDependencyError(
            f"Unsupported device '{requested}'. Use auto, cpu, or cuda."
        )

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError("PyTorch is not installed.") from exc

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise MMSDependencyError(
            "CUDA was requested but no CUDA-capable GPU is visible to PyTorch."
        )
    return requested


def load_mms_model(*, device: str, target_lang: str, model_id: str):
    cache_key = f"{device}|{target_lang}|{model_id}"
    if cache_key in _MMS_CACHE:
        return _MMS_CACHE[cache_key]

    try:
        from transformers import AutoProcessor, Wav2Vec2ForCTC  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError("transformers is not installed.") from exc

    runtime_device = choose_mms_device(device)
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
        return _read_audio_ffmpeg(audio_path, sample_rate=sample_rate)
    except MMSDependencyError:
        return _read_audio_python(audio_path, sample_rate=sample_rate)


def _read_audio_ffmpeg(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError("numpy is required for ffmpeg audio normalization.") from exc

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MMSDependencyError("ffmpeg is not installed.")

    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="ignore").strip()
        raise MMSDependencyError(
            f"ffmpeg failed to normalize audio: {error or 'unknown error'}"
        )

    audio = np.frombuffer(completed.stdout, dtype=np.float32)
    if audio.size == 0:
        raise MMSDependencyError(f"Unable to decode audio frames from {audio_path}.")

    audio_seconds = float(len(audio) / sample_rate)
    return audio, audio_seconds


def _read_audio_python(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        import av  # type: ignore
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError(
            "Missing audio dependencies. Install av, librosa, and numpy."
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


def _batched(iterable: list[Any], batch_size: int) -> list[list[Any]]:
    size = max(int(batch_size), 1)
    return [iterable[index : index + size] for index in range(0, len(iterable), size)]


def transcribe_mms_file(
    audio_path: str | Path,
    *,
    device: str = "auto",
    target_lang: str = "jam",
    model_id: str = "facebook/mms-1b-l1107",
    chunk_seconds: int = 25,
    batch_size: int = 4,
    sample_rate: int = 16_000,
) -> MMSTranscriptionResult:
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise MMSDependencyError("PyTorch is not installed.") from exc

    started = perf_counter()
    processor, model, runtime_device = load_mms_model(
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
    for batch in _batched(chunks, batch_size=batch_size):
        inputs = processor(
            batch,
            sampling_rate=sample_rate,
            return_tensors="pt",
            padding=True,
        )
        input_values = inputs.input_values.to(runtime_device)
        attention_mask = getattr(inputs, "attention_mask", None)
        if attention_mask is not None:
            attention_mask = attention_mask.to(runtime_device)
        with torch.inference_mode():
            logits = model(input_values, attention_mask=attention_mask).logits
        ids = torch.argmax(logits, dim=-1)
        decoded_chunks.extend(processor.batch_decode(ids))
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
