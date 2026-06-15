"""Standalone OmniASR helper for the Lightning speech API bundle."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


class OmniDependencyError(RuntimeError):
    """Raised when OmniASR dependencies are missing or invalid."""


@dataclass
class OmniTranscriptionResult:
    text: str
    model_id: str
    device: str
    target_lang: str
    audio_seconds: float
    chunk_count: int
    preprocessing_ms: int
    inference_ms: int
    total_ms: int
    load_ms: int = 0
    sample_rate: int = 16_000

    @property
    def realtime_factor(self) -> float | None:
        total_seconds = self.total_ms / 1000 if self.total_ms else 0
        if total_seconds <= 0:
            return None
        return self.audio_seconds / total_seconds


_OMNI_CACHE: dict[str, Any] = {}

_LANG_MAP = {
    "jam": "jam_Latn",
    "pat": "jam_Latn",
    "en": "eng_Latn",
    "eng": "eng_Latn",
    "es": "spa_Latn",
    "spa": "spa_Latn",
    "fr": "fra_Latn",
    "fra": "fra_Latn",
    "ht": "hat_Latn",
    "hat": "hat_Latn",
    "pt": "por_Latn",
    "por": "por_Latn",
}


def _fairseq2_cache_dir() -> Path:
    configured = os.getenv("FAIRSEQ2_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    xdg_cache = os.getenv("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache) / "fairseq2"
    return Path.home() / ".cache" / "fairseq2"


def normalize_omni_lang(target_lang: str | None) -> str:
    value = (target_lang or "jam_Latn").strip()
    if not value:
        return "jam_Latn"
    mapped = _LANG_MAP.get(value.lower())
    if mapped:
        return mapped
    if "_" not in value and value.isascii():
        return f"{value}_Latn"
    return value


def probe_omni_runtime() -> dict[str, Any]:
    info: dict[str, Any] = {
        "torch": False,
        "torch_version": None,
        "torchaudio": False,
        "torchaudio_version": None,
        "omnilingual_asr": False,
        "omnilingual_asr_version": None,
        "fairseq2": False,
        "fairseq2_version": None,
        "cuda": False,
        "cuda_device": None,
        "numpy": False,
        "ffmpeg": False,
        "model_cached_omni": False,
        "model_loaded_omni": False,
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

    for module_name, version_key in (
        ("torchaudio", "torchaudio_version"),
        ("omnilingual_asr", "omnilingual_asr_version"),
        ("fairseq2", "fairseq2_version"),
    ):
        try:
            module = __import__(module_name)
            info[module_name] = True
            info[version_key] = getattr(module, "__version__", None)
        except Exception:  # noqa: BLE001
            pass

    try:
        __import__("numpy")
        info["numpy"] = True
    except Exception:  # noqa: BLE001
        pass

    info["ffmpeg"] = shutil.which("ffmpeg") is not None

    cache = _fairseq2_cache_dir()
    if cache.exists():
        try:
            info["model_cached_omni"] = any(
                "omniasr" in path.name.lower()
                for path in cache.rglob("*")
            )
        except Exception:  # noqa: BLE001
            pass

    info["model_loaded_omni"] = bool(_OMNI_CACHE)
    return info


def choose_omni_device(requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise OmniDependencyError(
            f"Unsupported device '{requested}'. Use auto, cpu, or cuda."
        )

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError("PyTorch is not installed.") from exc

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise OmniDependencyError(
            "CUDA was requested but no CUDA-capable GPU is visible to PyTorch."
        )
    return requested


def _init_gang(device: str) -> None:
    try:
        import torch  # type: ignore
        from fairseq2.gang import _thread_local, create_fake_gangs  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError("fairseq2 is not installed.") from exc

    _thread_local.current_gangs = [create_fake_gangs(torch.device(device))]


def load_omni_pipeline(*, device: str, model_id: str):
    runtime_device = choose_omni_device(device)
    cache_key = f"{runtime_device}|{model_id}"
    if cache_key in _OMNI_CACHE:
        pipeline = _OMNI_CACHE[cache_key]
        return pipeline, runtime_device, 0

    try:
        from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError(
            "omnilingual-asr is not installed. Install omnilingual-asr, fairseq2, and silero-vad."
        ) from exc

    _init_gang(runtime_device)
    started = perf_counter()
    pipeline = ASRInferencePipeline(model_card=model_id, device=runtime_device)
    load_ms = int((perf_counter() - started) * 1000)
    _OMNI_CACHE[cache_key] = pipeline
    return pipeline, runtime_device, load_ms


def _read_audio(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        return _read_audio_ffmpeg(audio_path, sample_rate=sample_rate)
    except OmniDependencyError:
        return _read_audio_torchaudio(audio_path, sample_rate=sample_rate)


def _read_audio_ffmpeg(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError("numpy is required for ffmpeg audio normalization.") from exc

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise OmniDependencyError("ffmpeg is not installed.")

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
        raise OmniDependencyError(
            f"ffmpeg failed to normalize audio: {error or 'unknown error'}"
        )

    audio = np.frombuffer(completed.stdout, dtype=np.float32)
    if audio.size == 0:
        raise OmniDependencyError(f"Unable to decode audio frames from {audio_path}.")

    audio_seconds = float(len(audio) / sample_rate)
    return audio, audio_seconds


def _read_audio_torchaudio(audio_path: str | Path, *, sample_rate: int = 16_000):
    try:
        import torchaudio  # type: ignore
        import torchaudio.functional as taf  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError("torchaudio is required to decode audio.") from exc

    waveform, original_rate = torchaudio.load(str(audio_path))
    if original_rate != sample_rate:
        waveform = taf.resample(waveform, original_rate, sample_rate)
    if waveform.ndim > 1:
        waveform = waveform.mean(dim=0, keepdim=False)
    audio = waveform.detach().cpu().numpy()
    audio_seconds = float(len(audio) / sample_rate)
    return audio, audio_seconds


def _vad_chunk_audio(
    audio: Any,
    *,
    sample_rate: int = 16_000,
    max_chunk_seconds: int = 30,
) -> list[Any]:
    max_samples = max(int(max_chunk_seconds), 1) * sample_rate
    if len(audio) <= max_samples:
        return [audio]

    try:
        import torch  # type: ignore
        from silero_vad import get_speech_timestamps, load_silero_vad  # type: ignore

        vad = load_silero_vad()
        tensor = torch.from_numpy(audio).float()
        timestamps = get_speech_timestamps(tensor, vad, sampling_rate=sample_rate)
        if timestamps:
            chunks: list[Any] = []
            chunk_start = 0
            last_speech_end = 0
            for segment in timestamps:
                segment_start = int(segment["start"])
                segment_end = int(segment["end"])
                if segment_end - chunk_start > max_samples and last_speech_end > chunk_start:
                    chunks.append(audio[chunk_start:last_speech_end])
                    chunk_start = segment_start
                last_speech_end = segment_end
            if chunk_start < len(audio):
                chunks.append(audio[chunk_start:])
            if chunks:
                return chunks
    except Exception:  # noqa: BLE001
        pass

    return [
        audio[index : index + max_samples]
        for index in range(0, len(audio), max_samples)
    ]


def _write_chunk_wav(chunk: Any, *, sample_rate: int = 16_000) -> str:
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise OmniDependencyError("numpy is required to encode WAV chunks.") from exc

    pcm = (chunk * 32767).clip(-32768, 32767).astype(np.int16)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return tmp.name


def transcribe_omni_file(
    audio_path: str | Path,
    *,
    device: str = "auto",
    model_id: str = "omniASR_CTC_1B_v2",
    target_lang: str = "jam_Latn",
    chunk_seconds: int = 30,
    batch_size: int = 1,
    sample_rate: int = 16_000,
) -> OmniTranscriptionResult:
    started = perf_counter()
    normalized_target_lang = normalize_omni_lang(target_lang)
    pipeline, runtime_device, load_ms = load_omni_pipeline(
        device=device,
        model_id=model_id,
    )

    preprocess_started = perf_counter()
    audio, audio_seconds = _read_audio(audio_path, sample_rate=sample_rate)
    chunks = _vad_chunk_audio(
        audio,
        sample_rate=sample_rate,
        max_chunk_seconds=chunk_seconds,
    ) or [audio]
    tmp_paths = [
        _write_chunk_wav(chunk, sample_rate=sample_rate)
        for chunk in chunks
    ]
    preprocessing_ms = int((perf_counter() - preprocess_started) * 1000)

    inference_started = perf_counter()
    _init_gang(runtime_device)
    transcriptions: list[str] = []
    try:
        for tmp_path in tmp_paths:
            # The upstream CTC pipeline has been unreliable when a single
            # transcribe() call receives multiple chunk paths, so run one chunk
            # per call for correctness and let Modal scale requests out across
            # containers instead.
            transcriptions.extend(
                list(
                    pipeline.transcribe(
                        [tmp_path],
                        lang=[normalized_target_lang],
                        batch_size=1,
                    )
                )
            )
    finally:
        for tmp_path in tmp_paths:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    inference_ms = int((perf_counter() - inference_started) * 1000)
    total_ms = int((perf_counter() - started) * 1000)

    return OmniTranscriptionResult(
        text=" ".join(text.strip() for text in transcriptions if text.strip()).strip(),
        model_id=model_id,
        device=runtime_device,
        target_lang=normalized_target_lang,
        audio_seconds=round(audio_seconds, 3),
        chunk_count=len(chunks),
        preprocessing_ms=preprocessing_ms,
        inference_ms=inference_ms,
        total_ms=total_ms,
        load_ms=load_ms,
        sample_rate=sample_rate,
    )
