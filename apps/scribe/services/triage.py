"""Triage sandbox: Patois ASR experiments.

This module is intentionally lazy. transformers / torch are heavy
dependencies, MMS-1b-l1107 is ~4 GB, and they may not be installed in
every environment (especially the pilot). We import them inside each
loader function so the rest of WellNest works fine even when they
aren't there.

The user-facing flow:
  1. Doctor (or admin) uploads or records audio on /scribe/triage/
  2. They pick a backend (mms, t5_paraphrase, or cloud-passthrough)
  3. They pick a device (cpu / cuda)
  4. We run the chosen model and return the raw transcript
  5. Optionally we pipe that transcript through interpret_patois() to
     get clean clinical English the SOAP pipeline can consume

The whole feature can be hidden by setting SCRIBE_ENABLE_TRIAGE=False
(default) and not granting staff. Pilot doctors never see it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings


logger = logging.getLogger(__name__)


class TriageDependencyError(RuntimeError):
    """Raised when a Triage backend is requested but its dependencies are missing."""


@dataclass
class TriageResult:
    backend: str
    device: str
    raw_text: str
    duration_ms: int
    notes: str = ""


# ---- Capability probe -------------------------------------------------------

def probe_environment() -> dict[str, Any]:
    """Return a dict describing what Triage can and cannot do right now.

    Used by the UI to disable buttons and explain install steps.
    """
    info: dict[str, Any] = {
        "torch": False,
        "torch_version": None,
        "cuda": False,
        "cuda_device": None,
        "transformers": False,
        "transformers_version": None,
        "librosa": False,
        "device_default": settings.TRIAGE_DEFAULT_DEVICE,
        "model_cached_mms": False,
        "model_cached_t5": False,
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

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.exists():
        info["model_cached_mms"] = any(
            p.name.startswith("models--facebook--mms") for p in cache.iterdir()
        )
        info["model_cached_t5"] = any(
            p.name.startswith("models--google--flan-t5") or p.name.startswith("models--google--t5")
            for p in cache.iterdir()
        )
    return info


# ---- MMS Patois ASR ---------------------------------------------------------

_MMS_CACHE: dict[str, Any] = {}


def _load_mms(device: str = "cpu", target_lang: str = "jam"):
    """Load facebook/mms-1b-l1107 lazily and cache by device."""
    key = f"{device}|{target_lang}"
    if key in _MMS_CACHE:
        return _MMS_CACHE[key]

    try:
        import torch  # type: ignore
        from transformers import AutoProcessor, Wav2Vec2ForCTC  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "transformers + torch are not installed. Run:\n"
            "    pip install transformers torch torchaudio librosa soundfile"
        ) from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise TriageDependencyError(
            "CUDA was requested but no CUDA-capable GPU is visible to PyTorch. "
            "Install a CUDA build of torch matching your driver, or use device=cpu."
        )

    model_id = "facebook/mms-1b-l1107"
    logger.info("Loading %s for lang=%s on %s …", model_id, target_lang, device)
    processor = AutoProcessor.from_pretrained(model_id)
    model = Wav2Vec2ForCTC.from_pretrained(model_id)
    processor.tokenizer.set_target_lang(target_lang)
    model.load_adapter(target_lang)
    model = model.to(device)
    model.eval()
    _MMS_CACHE[key] = (processor, model, device)
    return _MMS_CACHE[key]


def transcribe_mms(audio_path: str | Path, *, device: str = "cpu", target_lang: str = "jam") -> str:
    """Run MMS-1b-l1107 on an audio file and return the raw transcript."""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
        import torch  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "Missing audio libs. Run: pip install librosa soundfile torchaudio"
        ) from exc

    processor, model, dev = _load_mms(device=device, target_lang=target_lang)

    audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)
    # Chunk anything > 28s — MMS performs best on <30s clips.
    chunk_size = 25 * 16000
    chunks = (
        [audio[i:i + chunk_size] for i in range(0, len(audio), chunk_size)]
        if len(audio) > chunk_size
        else [audio]
    )
    out: list[str] = []
    for ch in chunks:
        inputs = processor(ch, sampling_rate=16000, return_tensors="pt")
        input_values = inputs.input_values.to(dev)
        with torch.no_grad():
            logits = model(input_values).logits
        ids = torch.argmax(logits, dim=-1)
        out.append(processor.batch_decode(ids)[0])
    return " ".join(out).strip()


# ---- T5 paraphrase / translate (text-side helper) ---------------------------

_T5_CACHE: dict[str, Any] = {}


def _load_t5(device: str = "cpu", model_id: str = "google/flan-t5-base"):
    key = f"{device}|{model_id}"
    if key in _T5_CACHE:
        return _T5_CACHE[key]
    try:
        import torch  # type: ignore
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "transformers + torch are not installed. Run:\n"
            "    pip install transformers torch sentencepiece"
        ) from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise TriageDependencyError(
            "CUDA requested but no CUDA-capable GPU is visible to PyTorch."
        )

    logger.info("Loading %s on %s …", model_id, device)
    tok = AutoTokenizer.from_pretrained(model_id)
    mdl = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)
    mdl.eval()
    _T5_CACHE[key] = (tok, mdl, device)
    return _T5_CACHE[key]


def t5_rewrite(text: str, *, instruction: str, device: str = "cpu",
               model_id: str = "google/flan-t5-base", max_new_tokens: int = 256) -> str:
    """Generic FLAN-T5 instruction-tuned rewrite. Cheap CPU-friendly model."""
    try:
        import torch  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError("torch not installed") from exc

    tok, mdl, dev = _load_t5(device=device, model_id=model_id)
    prompt = f"{instruction}\n\nInput: {text}\nOutput:"
    inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=1024).to(dev)
    with torch.no_grad():
        out = mdl.generate(**inputs, max_new_tokens=max_new_tokens, num_beams=4)
    return tok.decode(out[0], skip_special_tokens=True)
