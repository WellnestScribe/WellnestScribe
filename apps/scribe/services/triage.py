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
        "noisereduce": False,
        "deepfilternet": False,
        "pyannote": False,
        "diarize_lib": False,
        "device_default": settings.TRIAGE_DEFAULT_DEVICE,
        "model_cached_mms": False,
        "model_cached_t5": False,
        "model_cached_gemma": False,
        "model_cached_qwen": False,
        "model_cached_local_llm": False,
        "local_llm_dir": "",
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
    for pkg, key in (
        ("noisereduce", "noisereduce"),
        ("df", "deepfilternet"),
        ("pyannote.audio", "pyannote"),
        ("diarize", "diarize_lib"),
    ):
        try:
            __import__(pkg)
            info[key] = True
        except Exception:  # noqa: BLE001
            pass

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.exists():
        items = list(cache.iterdir())
        info["model_cached_mms"] = any(p.name.startswith("models--facebook--mms") for p in items)
        info["model_cached_t5"] = any(
            p.name.startswith("models--google--flan-t5") or p.name.startswith("models--google--t5")
            for p in items
        )
        info["model_cached_gemma"] = any(p.name.startswith("models--google--gemma") for p in items)
        info["model_cached_qwen"] = any(p.name.startswith("models--Qwen--") for p in items)

    # Local <BASE_DIR>/models/ fallback for any small interpreter LLM.
    for slug in ("Qwen--Qwen3-1.7B", "Qwen3-1.7B", "google--gemma-4-E2B", "gemma-4-E2B"):
        p = settings.BASE_DIR / "models" / slug
        if p.exists() and (p / "config.json").exists():
            info["local_llm_dir"] = str(p)
            info["model_cached_local_llm"] = True
            break
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

    #audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)

    import av
    import numpy as np

    container = av.open(str(audio_path))
    samples = []
    for frame in container.decode(audio=0):
        arr = frame.to_ndarray()
        if arr.ndim > 1:
            arr = arr.mean(axis=0)
        samples.append(arr)
    audio = np.concatenate(samples).astype(np.float32)
    # resample to 16kHz if needed
    import librosa
    audio = librosa.resample(audio, orig_sr=container.streams.audio[0].sample_rate, target_sr=16000)




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


# ---- Omni-ASR (Meta omnilingual / generic Whisper-style ASR) ---------------

_OMNI_CACHE: dict[str, Any] = {}


def _load_omni(device: str = "cpu", model_id: str = "facebook/omnilingual-asr-7b-ctc"):
    """Load any HuggingFace seq2seq or CTC ASR model lazily.

    `model_id` is configurable so you can test multiple Meta releases
    (omnilingual-asr 7B / 3B / 700M variants, seamless-m4t, voxtral, etc.).
    """
    key = f"{device}|{model_id}"
    if key in _OMNI_CACHE:
        return _OMNI_CACHE[key]

    try:
        import torch  # type: ignore
        from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq, AutoModelForCTC  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "transformers + torch not installed.\n"
            "    pip install transformers torch torchaudio librosa soundfile"
        ) from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise TriageDependencyError(
            "CUDA requested but no CUDA-capable GPU is visible to PyTorch."
        )

    logger.info("Loading omni model %s on %s …", model_id, device)
    processor = AutoProcessor.from_pretrained(model_id)
    # Try seq2seq (Whisper-style) first; fall back to CTC (Wav2Vec-style).
    try:
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id)
        kind = "seq2seq"
    except Exception:  # noqa: BLE001
        model = AutoModelForCTC.from_pretrained(model_id)
        kind = "ctc"
    model = model.to(device)
    model.eval()
    _OMNI_CACHE[key] = (processor, model, device, kind)
    return _OMNI_CACHE[key]


def transcribe_omni(audio_path: str | Path, *, device: str = "cpu",
                    model_id: str = "facebook/omnilingual-asr-7b-ctc",
                    language: str | None = None) -> str:
    try:
        import librosa  # type: ignore
        import torch  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "Missing audio libs. Run: pip install librosa soundfile torchaudio"
        ) from exc

    processor, model, dev, kind = _load_omni(device=device, model_id=model_id)
    audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)

    chunk_size = 25 * 16000
    chunks = (
        [audio[i:i + chunk_size] for i in range(0, len(audio), chunk_size)]
        if len(audio) > chunk_size
        else [audio]
    )
    out: list[str] = []
    for ch in chunks:
        inputs = processor(ch, sampling_rate=16000, return_tensors="pt")
        if hasattr(inputs, "input_values"):
            input_tensor = inputs.input_values.to(dev)
        else:
            input_tensor = inputs.input_features.to(dev)
        with torch.no_grad():
            if kind == "seq2seq":
                gen_kwargs = {"max_new_tokens": 444}
                if language:
                    gen_kwargs["language"] = language
                ids = model.generate(input_tensor, **gen_kwargs)
                text = processor.batch_decode(ids, skip_special_tokens=True)[0]
            else:
                logits = model(input_tensor).logits
                ids = torch.argmax(logits, dim=-1)
                text = processor.batch_decode(ids)[0]
        out.append(text)
    return " ".join(out).strip()


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


# ---- Gemma 4 E2B local (Patois → clinical English on CPU/GPU) --------------

_GEMMA_CACHE: dict[str, Any] = {}


def _resolve_local_model_dir(model_id: str) -> Path | None:
    """If the user manually downloaded the safetensors + tokenizer files into
    <BASE_DIR>/models/<slug>/  load from there instead of HuggingFace hub.

    Slug = model_id with '/' replaced by '--', matching HF cache convention.
    Required files in the folder: config.json + tokenizer.json (+ tokenizer_config.json)
    + model.safetensors (or sharded model-*.safetensors + model.safetensors.index.json).
    """
    from django.conf import settings  # local import to avoid django at import-time
    slug = model_id.replace("/", "--")
    candidates = [
        settings.BASE_DIR / "models" / slug,
        settings.BASE_DIR / "models" / model_id.split("/")[-1],
    ]
    for p in candidates:
        if p.exists() and (p / "config.json").exists():
            return p
    return None


def _load_gemma(device: str = "cpu", model_id: str = "Qwen/Qwen3-1.7B"):
    """Lazy-load a small instruction-tuned LLM (Qwen / Gemma / any HF
    causal LM) on CPU/CUDA. The default is Qwen3-1.7B (~1.7 B params,
    fast on consumer hardware). Earlier Gemma weights still load if you
    pass their model id.

    Resolution order:
      1. <BASE_DIR>/models/<slug>/   (slug = model_id with '/' → '--')
      2. <BASE_DIR>/models/<short>/  (last path component)
      3. HuggingFace hub by model_id (downloads to ~/.cache/huggingface/)
    """
    key = f"{device}|{model_id}"
    if key in _GEMMA_CACHE:
        return _GEMMA_CACHE[key]

    try:
        import torch  # type: ignore
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError(
            "transformers + torch not installed. "
            "Click 'Install (CPU)' or 'Install (CUDA 12.1)' in the Triage probe panel."
        ) from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise TriageDependencyError(
            "CUDA requested but no CUDA-capable GPU is visible to PyTorch. "
            "Install a CUDA build of torch — Triage panel has a "
            "'Reinstall torch with CUDA 12.1 (force)' button."
        )

    local = _resolve_local_model_dir(model_id)
    source = str(local) if local else model_id
    if local:
        logger.info("Loading %s on %s from local folder %s …", model_id, device, local)
    else:
        logger.info("Loading %s on %s from HuggingFace hub …", model_id, device)

    tok = AutoTokenizer.from_pretrained(source)
    dtype = torch.float16 if device == "cuda" else torch.float32
    mdl = AutoModelForCausalLM.from_pretrained(source, torch_dtype=dtype)
    mdl = mdl.to(device)
    mdl.eval()

    # CPU multi-thread hint — defaults to physical core count, big win on CPU.
    try:
        import os
        if device == "cpu":
            torch.set_num_threads(max(1, os.cpu_count() or 1))
    except Exception:  # noqa: BLE001
        pass

    _GEMMA_CACHE[key] = (tok, mdl, device)
    return _GEMMA_CACHE[key]


_GEMMA_PATOIS_PROMPT = (
    "You are a Jamaican Patois-to-clinical-English medical interpreter. "
    "Read the raw Patois transcript phonetically and rewrite it as neutral "
    "clinical English in third person. Capture every symptom, time course, "
    "and herbal remedy. Tag herbs as [HERBAL SUPPLEMENT]. Flag unintelligible "
    "parts with [unclear: \"...\"]. Output ONLY the rewritten clinical English "
    "— no commentary.\n\n"
    "Patois transcript:\n{transcript}\n\n"
    "Clinical English:"
)


def gemma_interpret_patois(text: str, *, device: str = "cpu",
                           model_id: str = "Qwen/Qwen3-1.7B",
                           max_new_tokens: int = 400) -> str:
    """Run a small local Gemma to interpret Patois on the host CPU/GPU."""
    try:
        import torch  # type: ignore
    except ImportError as exc:  # noqa: BLE001
        raise TriageDependencyError("torch not installed") from exc

    tok, mdl, dev = _load_gemma(device=device, model_id=model_id)
    prompt = _GEMMA_PATOIS_PROMPT.format(transcript=text or "")

    # Most Gemma checkpoints expose a chat template; fall back to raw prompt.
    try:
        messages = [{"role": "user", "content": prompt}]
        input_ids = tok.apply_chat_template(
            messages, return_tensors="pt", add_generation_prompt=True
        ).to(dev)
    except Exception:  # noqa: BLE001
        input_ids = tok(prompt, return_tensors="pt").input_ids.to(dev)

    with torch.no_grad():
        out_ids = mdl.generate(
            input_ids,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=0.0,
            repetition_penalty=1.05,
        )
    # Trim the prompt off the front so we only return the completion.
    completion_ids = out_ids[0][input_ids.shape[-1]:]
    return tok.decode(completion_ids, skip_special_tokens=True).strip()
