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
import os
import time
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
        "nemo": False,
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
        "model_cached_parakeet": False,
        "model_cached_local_llm": False,
        "local_llm_dir": "",
        "omnilingual_asr": False,
        "silero_vad": False,
        "jiwer": False,
        "model_cached_omni": False,
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
        import nemo  # noqa: F401  # type: ignore
        info["nemo"] = True
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
        ("omnilingual_asr", "omnilingual_asr"),
        ("silero_vad", "silero_vad"),
        ("jiwer", "jiwer"),
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
        info["model_cached_parakeet"] = any(p.name.startswith("models--nvidia--parakeet") for p in items)

    # Local <BASE_DIR>/models/ fallback for any small interpreter LLM.
    for slug in ("Qwen--Qwen3-1.7B", "Qwen3-1.7B", "google--gemma-4-E2B", "gemma-4-E2B"):
        p = settings.BASE_DIR / "models" / slug
        if p.exists() and (p / "config.json").exists():
            info["local_llm_dir"] = str(p)
            info["model_cached_local_llm"] = True
            break
    # fairseq2 asset cache — weights land in ~/.cache/fairseq2/assets/<hash>/
    try:
        _f2_root = Path.home() / ".cache" / "fairseq2"
        for _f2_dir in (
            _f2_root / "assets",
            _f2_root / "models",
            _f2_root,
        ):
            if _f2_dir.exists():
                if any(
                    "omni" in f.name.lower()
                    for d in _f2_dir.iterdir() if d.is_dir()
                    for f in d.iterdir()
                ):
                    info["model_cached_omni"] = True
                break
    except Exception:  # noqa: BLE001
        pass
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


# ---- OmniASR — Meta omnilingual CTC (ASRInferencePipeline / fairseq2) ------

_OMNI_CACHE: dict[str, tuple[Any, int]] = {}


def _check_omni_lang_support(lang_code: str) -> bool:
    """Return True if lang_code is in omnilingual_asr supported_langs."""
    try:
        from omnilingual_asr.models.wav2vec2_llama.lang_ids import supported_langs  # type: ignore
        return lang_code in supported_langs
    except Exception:  # noqa: BLE001
        return True  # optimistic if module layout differs


def _vad_chunk_audio(
    audio: Any,
    sample_rate: int = 16000,
    max_chunk_seconds: int = 30,
) -> list:
    """Split float32 audio into ≤max_chunk_seconds chunks at natural speech silences.

    Uses silero-VAD when available; falls back to fixed-size splitting.
    CTC models cap out at 40 s — default max_chunk_seconds=30 keeps headroom.
    """
    max_samples = max_chunk_seconds * sample_rate
    if len(audio) <= max_samples:
        return [audio]

    try:
        import torch  # type: ignore
        from silero_vad import get_speech_timestamps, load_silero_vad  # type: ignore

        vad = load_silero_vad()
        tensor = torch.from_numpy(audio).float()
        timestamps = get_speech_timestamps(tensor, vad, sampling_rate=sample_rate)

        if timestamps:
            chunks: list = []
            chunk_start = 0
            last_speech_end = 0
            for seg in timestamps:
                seg_end = int(seg["end"])
                seg_start = int(seg["start"])
                if seg_end - chunk_start > max_samples and last_speech_end > chunk_start:
                    chunks.append(audio[chunk_start:last_speech_end])
                    chunk_start = seg_start
                last_speech_end = seg_end
            if chunk_start < len(audio):
                chunks.append(audio[chunk_start:])
            if chunks:
                return chunks
    except Exception:  # noqa: BLE001
        pass  # silero-vad unavailable — fall through to fixed split

    return [audio[i : i + max_samples] for i in range(0, len(audio), max_samples)]


def _load_omni(
    device: str = "cpu",
    model_card: str = "omniASR_CTC_1B",
) -> tuple[Any, int]:
    """Lazy-load ASRInferencePipeline; return (pipeline, load_ms_on_first_call).

    Subsequent calls return (cached_pipeline, 0).
    """
    key = f"{device}|{model_card}"
    if key in _OMNI_CACHE:
        return _OMNI_CACHE[key][0], 0

    try:
        from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError(
            "omnilingual-asr is not installed.\n"
            "    pip install omnilingual-asr jiwer silero-vad\n"
            "Also requires libsndfile:\n"
            "    brew install libsndfile  (macOS)\n"
            "    apt install libsndfile1  (Linux)"
        ) from exc

    omni_cache_dir = getattr(settings, "OMNI_CACHE_DIR", "")
    if omni_cache_dir:
        os.environ.setdefault("FAIRSEQ2_CACHE_DIR", omni_cache_dir)
        logger.info("omniASR: FAIRSEQ2_CACHE_DIR=%s", omni_cache_dir)

    logger.info("Loading omniASR pipeline (%s) on %s …", model_card, device)
    t0 = time.perf_counter()
    pipeline = ASRInferencePipeline(model_card=model_card, device=device or None)
    load_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("omniASR %s loaded in %d ms", model_card, load_ms)

    _OMNI_CACHE[key] = (pipeline, load_ms)
    return pipeline, load_ms


def transcribe_gradio(
    audio_path: str | Path,
    *,
    gradio_url: str,
    target_lang: str = "jam_Latn",
    model_label: str = "CTC 300M  (faster, ~1.2 GB)",
    batch_size: int = 4,
    reference: str = "",
) -> dict:
    """Call a running Gradio omniASR Colab endpoint and return a result dict
    matching the shape of transcribe_omni()."""
    try:
        from gradio_client import Client, handle_file  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError(
            "gradio_client not installed.\n    pip install gradio_client"
        ) from exc

    lang_label_map = {
        "jam_Latn": "Jamaican Creole (Patois) — jam_Latn",
        "eng_Latn": "English — eng_Latn",
        "spa_Latn": "Spanish — spa_Latn",
        "fra_Latn": "French — fra_Latn",
        "hat_Latn": "Haitian Creole — hat_Latn",
        "por_Latn": "Portuguese — por_Latn",
    }
    lang_label = lang_label_map.get(target_lang, target_lang)

    t0 = time.perf_counter()
    client = Client(gradio_url, verbose=False)
    transcript, stats, accuracy = client.predict(
        handle_file(str(audio_path)),
        None,           # mic_audio — not used via API
        lang_label,
        model_label,
        batch_size,
        reference,
        api_name="/predict",
    )
    total_ms = int((time.perf_counter() - t0) * 1000)

    # Parse timing from stats string e.g. "Audio: 12.3s | Chunks: 1 | Prep: 45ms | Inference: 820ms | RTF: 0.067x"
    import re as _re
    def _extract(pattern, s, cast=float):
        m = _re.search(pattern, s or "")
        return cast(m.group(1)) if m else None

    return {
        "text": transcript,
        "model_card": model_label,
        "device": "cuda (gradio)",
        "target_lang": target_lang,
        "lang_supported": True,
        "audio_seconds": _extract(r"Audio:\s*([\d.]+)", stats),
        "chunk_count": _extract(r"Chunks:\s*(\d+)", stats, int),
        "load_ms": 0,
        "preprocessing_ms": _extract(r"Prep:\s*(\d+)", stats, int),
        "inference_ms": _extract(r"Inference:\s*(\d+)", stats, int),
        "total_ms": total_ms,
        "realtime_factor": _extract(r"RTF:\s*([\d.]+)", stats),
        "accuracy_str": accuracy,
    }


def transcribe_omni(
    audio_path: str | Path,
    *,
    device: str = "cpu",
    model_card: str = "omniASR_CTC_1B",
    target_lang: str = "jam_Latn",
    batch_size: int = 4,
    max_chunk_seconds: int = 30,
) -> dict:
    """Transcribe with omniASR CTC via VAD-chunking + batched inference.

    Returns a dict with: text, model_card, device, target_lang, lang_supported,
    audio_seconds, chunk_count, load_ms, preprocessing_ms, inference_ms,
    total_ms, realtime_factor.
    """
    import tempfile
    import wave as _wave

    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError("numpy not installed. Run: pip install numpy") from exc

    lang_supported = _check_omni_lang_support(target_lang)
    if not lang_supported:
        logger.warning(
            "omniASR: lang %r not in supported_langs — try jam_Latn for Jamaican Creole.",
            target_lang,
        )

    # fairseq2 gang context is thread-local; reinitialise it for this thread
    # so cached pipelines work when called from Django's background threads.
    try:
        from fairseq2.gang import create_fake_gangs, _thread_local
        import torch as _torch
        _dev = _torch.device(device if device != "cuda" or _torch.cuda.is_available() else "cpu")
        _thread_local.current_gangs = [create_fake_gangs(_dev)]
    except Exception:
        pass

    pipeline, load_ms = _load_omni(device=device, model_card=model_card)

    # Load and resample audio to 16 kHz mono float32.
    t_pre = time.perf_counter()
    try:
        import av  # type: ignore
        import librosa  # type: ignore

        container = av.open(str(audio_path))
        samples: list = []
        native_sr: int | None = None
        for frame in container.decode(audio=0):
            if native_sr is None:
                native_sr = frame.sample_rate
            arr = frame.to_ndarray()
            if arr.ndim > 1:
                arr = arr.mean(axis=0)
            samples.append(arr.astype(np.float32))
        audio = np.concatenate(samples)
        if native_sr and native_sr != 16000:
            audio = librosa.resample(audio, orig_sr=native_sr, target_sr=16000)
    except Exception:  # noqa: BLE001
        try:
            import librosa  # type: ignore
        except ImportError as exc:
            raise TriageDependencyError(
                "librosa is required. Run: pip install librosa soundfile"
            ) from exc
        audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)

    audio_seconds = len(audio) / 16000
    chunks = _vad_chunk_audio(audio, sample_rate=16000, max_chunk_seconds=max_chunk_seconds)
    preprocessing_ms = int((time.perf_counter() - t_pre) * 1000)

    # Write each chunk to a temp WAV so fairseq2 can load from file paths.
    tmp_paths: list[Path] = []
    try:
        for chunk in chunks:
            audio_int16 = (chunk * 32767).clip(-32768, 32767).astype(np.int16)
            tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tf.close()
            with _wave.open(tf.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            tmp_paths.append(Path(tf.name))

        lang_list = [target_lang] * len(tmp_paths)
        t_inf = time.perf_counter()
        transcriptions: list[str] = pipeline.transcribe(
            [str(p) for p in tmp_paths],
            lang=lang_list,
            batch_size=batch_size,
        )
        inference_ms = int((time.perf_counter() - t_inf) * 1000)
    finally:
        for p in tmp_paths:
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                pass

    total_ms = load_ms + preprocessing_ms + inference_ms
    rtf = round(inference_ms / 1000 / audio_seconds, 4) if audio_seconds > 0 else None

    return {
        "text": " ".join(t.strip() for t in transcriptions if t.strip()),
        "model_card": model_card,
        "device": device,
        "target_lang": target_lang,
        "lang_supported": lang_supported,
        "audio_seconds": round(audio_seconds, 3),
        "chunk_count": len(chunks),
        "load_ms": load_ms,
        "preprocessing_ms": preprocessing_ms,
        "inference_ms": inference_ms,
        "total_ms": total_ms,
        "realtime_factor": rtf,
    }


def _compute_wer_cer(reference: str, hypothesis: str) -> dict:
    """Compute WER + CER with basic normalization using jiwer.

    CER is the headline metric for Patois — WER overpunishes spelling
    variation that is phonetically equivalent.
    """
    try:
        import jiwer  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError("jiwer not installed. Run: pip install jiwer") from exc

    import re

    def _norm(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s']", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    ref_n = _norm(reference)
    hyp_n = _norm(hypothesis)
    return {
        "wer": round(jiwer.wer(ref_n, hyp_n), 4),
        "cer": round(jiwer.cer(ref_n, hyp_n), 4),
    }


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

    # apply_chat_template returns a plain tensor (Gemma) or BatchEncoding (Qwen).
    # Normalise both into a dict so generate() always receives **kwargs.
    # enable_thinking=False suppresses Qwen3 <think> blocks; ignored by other models.
    try:
        messages = [{"role": "user", "content": prompt}]
        try:
            enc = tok.apply_chat_template(
                messages, return_tensors="pt", add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            enc = tok.apply_chat_template(
                messages, return_tensors="pt", add_generation_prompt=True
            )
        if hasattr(enc, "input_ids"):
            # BatchEncoding — move every tensor to device
            gen_inputs = {k: v.to(dev) for k, v in enc.items()}
        else:
            # Plain tensor
            gen_inputs = {"input_ids": enc.to(dev)}
    except Exception:  # noqa: BLE001
        gen_inputs = {"input_ids": tok(prompt, return_tensors="pt").input_ids.to(dev)}

    prompt_len = gen_inputs["input_ids"].shape[-1]

    with torch.no_grad():
        out_ids = mdl.generate(
            **gen_inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            repetition_penalty=1.05,
        )
    # Trim the prompt off the front so we only return the completion.
    completion_ids = out_ids[0][prompt_len:]
    text = tok.decode(completion_ids, skip_special_tokens=True).strip()
    # Strip Qwen3 chain-of-thought blocks that leak when thinking mode is on.
    import re as _re
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
    return text


# ---- NVIDIA Parakeet TDT 0.6B v2 (NeMo ASR, English) -----------------------

_PARAKEET_CACHE: dict[str, Any] = {}


def _load_parakeet(device: str = "cpu"):
    """Lazy-load nvidia/parakeet-tdt-0.6b-v2 via NeMo. Cached per device."""
    if device in _PARAKEET_CACHE:
        return _PARAKEET_CACHE[device]

    try:
        import nemo.collections.asr as nemo_asr  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError(
            "NeMo ASR not installed. From a terminal run:\n"
            "    pip install nemo_toolkit[asr]\n"
            "First download is ~600 MB of model weights."
        ) from exc

    try:
        import torch  # type: ignore
        if device == "cuda" and not torch.cuda.is_available():
            raise TriageDependencyError(
                "CUDA requested but no CUDA-capable GPU visible to PyTorch."
            )
    except ImportError as exc:
        raise TriageDependencyError("torch not installed") from exc

    logger.info("Loading nvidia/parakeet-tdt-0.6b-v2 on %s …", device)
    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
    if device == "cuda":
        model = model.cuda()
    else:
        model = model.cpu()
    model.eval()
    _PARAKEET_CACHE[device] = model
    return model


def transcribe_parakeet(audio_path: str | Path, *, device: str = "cpu") -> str:
    """Run nvidia/parakeet-tdt-0.6b-v2 and return the English transcript.

    Converts input audio to 16kHz mono WAV (what Parakeet expects), runs
    inference on CPU (default), then cleans up the temp file.
    """
    import os
    import tempfile

    try:
        import librosa  # type: ignore
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError(
            "Missing audio libs. Run: pip install librosa soundfile"
        ) from exc

    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError("torch not installed") from exc

    model = _load_parakeet(device=device)

    audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        sf.write(tmp_path, audio, 16000)
        with torch.no_grad():
            output = model.transcribe([tmp_path])
        # NeMo returns Hypothesis objects or plain strings depending on version.
        if output:
            first = output[0]
            text = first.text if hasattr(first, "text") else str(first)
        else:
            text = ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return text.strip()


# TEMPORARY — Modal L4 GPU endpoint for ambient-mode latency testing.
# Remove this function once the testing phase is complete.
def _convert_webm_to_wav(src: Path) -> "Path | None":
    """Best-effort webm→WAV via ffmpeg. Returns temp WAV path or None."""
    import subprocess
    import tempfile

    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", tmp.name],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and Path(tmp.name).stat().st_size > 100:
            return Path(tmp.name)
        Path(tmp.name).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return None


def transcribe_modal_mms(
    audio_path: str | Path,
    *,
    target_lang: str = "jam",
) -> dict:
    """POST audio to the Modal-hosted MMS endpoint and return the full response dict.

    Response keys: ok, transcript, audio_seconds, preprocessing_ms,
    inference_ms, total_ms, realtime_factor, model_id, device.
    """
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise TriageDependencyError(
            "requests not installed. Run: pip install requests"
        ) from exc

    url = settings.MODAL_MMS_URL
    if not url:
        raise TriageDependencyError(
            "MODAL_MMS_URL is not set in .env. "
            "Add it or switch AMBIENT_BACKEND=local."
        )

    headers = {}
    if settings.MODAL_MMS_API_KEY:
        headers["X-API-Key"] = settings.MODAL_MMS_API_KEY

    src = Path(audio_path)
    tmp_wav: "Path | None" = None
    # Browser webm files lack duration metadata; convert to WAV so Modal's
    # duration pre-check doesn't read 0 s and reject valid recordings.
    if src.suffix.lower() in {".webm", ".ogg", ".opus"}:
        tmp_wav = _convert_webm_to_wav(src)

    send_path = tmp_wav if tmp_wav else src
    try:
        with open(send_path, "rb") as f:
            resp = requests.post(
                url,
                headers=headers,
                files={"file": (send_path.name, f, "audio/wav" if tmp_wav else "audio/webm")},
                data={"backend": "mms", "target_lang": target_lang},
                timeout=300,
            )
    finally:
        if tmp_wav:
            tmp_wav.unlink(missing_ok=True)

    if not resp.ok:
        body = ""
        try:
            body = resp.json().get("detail") or resp.json().get("error") or resp.text[:300]
        except Exception:  # noqa: BLE001
            body = resp.text[:300]
        raise RuntimeError(f"Modal MMS HTTP {resp.status_code}: {body}")

    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Modal MMS error: {data.get('error') or data}")
    return data
