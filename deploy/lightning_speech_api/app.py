"""FastAPI service for running Whisper, MMS, and OmniASR on GPU hosts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from mms_asr import (
    MMSDependencyError,
    load_mms_model,
    probe_mms_runtime,
    transcribe_mms_file,
)
from omni_asr import (
    OmniDependencyError,
    load_omni_pipeline,
    probe_omni_runtime,
    transcribe_omni_file,
)
from whisper_asr import (
    WhisperDependencyError,
    load_whisper_model,
    probe_whisper_runtime,
    transcribe_whisper_file,
)


APP_TITLE = os.getenv("WELLNEST_SPEECH_API_TITLE", "WellNest Speech API")
DEFAULT_BACKEND = os.getenv("LIGHTNING_SPEECH_BACKEND", "whisper").strip().lower()
DEFAULT_DEVICE = os.getenv("LIGHTNING_SPEECH_DEVICE", "auto").strip().lower()
DEFAULT_MAX_FILE_MB = int(os.getenv("LIGHTNING_SPEECH_MAX_FILE_MB", "100"))
DEFAULT_WHISPER_MODEL_ID = os.getenv("LIGHTNING_WHISPER_MODEL_ID", "large-v3").strip()
DEFAULT_WHISPER_LANGUAGE = os.getenv("LIGHTNING_WHISPER_LANGUAGE", "en").strip()
DEFAULT_WHISPER_TASK = os.getenv("LIGHTNING_WHISPER_TASK", "transcribe").strip()
DEFAULT_WHISPER_COMPUTE_TYPE = os.getenv("LIGHTNING_WHISPER_COMPUTE_TYPE", "auto").strip()
DEFAULT_WHISPER_BEAM_SIZE = int(os.getenv("LIGHTNING_WHISPER_BEAM_SIZE", "5"))
DEFAULT_MMS_MODEL_ID = os.getenv("LIGHTNING_MMS_MODEL_ID", "facebook/mms-1b-l1107").strip()
DEFAULT_MMS_TARGET_LANG = os.getenv("LIGHTNING_MMS_TARGET_LANG", "jam").strip()
DEFAULT_MMS_CHUNK_SECONDS = int(os.getenv("LIGHTNING_MMS_CHUNK_SECONDS", "25"))
DEFAULT_MMS_BATCH_SIZE = int(os.getenv("LIGHTNING_MMS_BATCH_SIZE", "4"))
DEFAULT_OMNI_MODEL_ID = os.getenv("LIGHTNING_OMNI_MODEL_ID", "omniASR_CTC_1B_v2").strip()
DEFAULT_OMNI_TARGET_LANG = os.getenv("LIGHTNING_OMNI_TARGET_LANG", "jam_Latn").strip()
DEFAULT_OMNI_CHUNK_SECONDS = int(os.getenv("LIGHTNING_OMNI_CHUNK_SECONDS", "30"))
DEFAULT_OMNI_BATCH_SIZE = int(os.getenv("LIGHTNING_OMNI_BATCH_SIZE", "1"))
API_TOKEN = os.getenv("LIGHTNING_SPEECH_API_TOKEN", os.getenv("LIGHTNING_MMS_API_TOKEN", "")).strip()
PRELOAD_MODELS = os.getenv("LIGHTNING_PRELOAD_MODELS", "").strip().lower() in {"1", "true", "yes"}
PRELOAD_BACKENDS = {
    value.strip().lower()
    for value in os.getenv("LIGHTNING_PRELOAD_BACKENDS", "").split(",")
    if value.strip()
}

app = FastAPI(title=APP_TITLE, version="0.3.0")


def _check_auth(
    authorization: str | None,
    x_api_key: str | None = None,
) -> None:
    if not API_TOKEN:
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization == expected or x_api_key == API_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
def root(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    return {
        "ok": True,
        "service": APP_TITLE,
        "default_backend": DEFAULT_BACKEND,
        "preload_models": PRELOAD_MODELS,
        "preload_backends": sorted(_selected_preload_backends()) if PRELOAD_MODELS else [],
        "endpoints": [
            "/health",
            "/warm",
            "/transcribe/file",
            "/transcribe/whisper/file",
            "/transcribe/mms/file",
            "/transcribe/omni/file",
        ],
    }


@app.get("/health")
def health(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    return {
        "ok": True,
        "service": APP_TITLE,
        "default_backend": DEFAULT_BACKEND,
        "default_device": DEFAULT_DEVICE,
        "preload_models": PRELOAD_MODELS,
        "preload_backends": sorted(_selected_preload_backends()) if PRELOAD_MODELS else [],
        "defaults": {
            "whisper_model_id": DEFAULT_WHISPER_MODEL_ID,
            "whisper_language": DEFAULT_WHISPER_LANGUAGE,
            "whisper_task": DEFAULT_WHISPER_TASK,
            "whisper_compute_type": DEFAULT_WHISPER_COMPUTE_TYPE,
            "mms_model_id": DEFAULT_MMS_MODEL_ID,
            "mms_target_lang": DEFAULT_MMS_TARGET_LANG,
            "mms_chunk_seconds": DEFAULT_MMS_CHUNK_SECONDS,
            "mms_batch_size": DEFAULT_MMS_BATCH_SIZE,
            "omni_model_id": DEFAULT_OMNI_MODEL_ID,
            "omni_target_lang": DEFAULT_OMNI_TARGET_LANG,
            "omni_chunk_seconds": DEFAULT_OMNI_CHUNK_SECONDS,
            "omni_batch_size": DEFAULT_OMNI_BATCH_SIZE,
        },
        "runtime": {
            "mms": probe_mms_runtime(),
            "omni": probe_omni_runtime(),
            "whisper": probe_whisper_runtime(),
        },
    }


def _selected_preload_backends() -> set[str]:
    return PRELOAD_BACKENDS or {DEFAULT_BACKEND}


def _warm_backend(
    backend: str,
    *,
    device: str,
    model_id: str | None,
    compute_type: str | None = None,
    target_lang: str | None = None,
) -> dict[str, str]:
    normalized_backend = _normalized_backend(backend)
    if normalized_backend == "whisper":
        _, runtime_device, runtime_compute_type = load_whisper_model(
            device=device or DEFAULT_DEVICE,
            model_id=(model_id or DEFAULT_WHISPER_MODEL_ID),
            compute_type=(compute_type or DEFAULT_WHISPER_COMPUTE_TYPE or "auto"),
        )
        return {
            "backend": "whisper",
            "device": runtime_device,
            "model_id": model_id or DEFAULT_WHISPER_MODEL_ID,
            "compute_type": runtime_compute_type,
        }

    if normalized_backend == "omni":
        _, runtime_device, _ = load_omni_pipeline(
            device=device or DEFAULT_DEVICE,
            model_id=(model_id or DEFAULT_OMNI_MODEL_ID),
        )
        return {
            "backend": "omni",
            "device": runtime_device,
            "model_id": model_id or DEFAULT_OMNI_MODEL_ID,
            "target_lang": target_lang or DEFAULT_OMNI_TARGET_LANG,
        }

    _, _, runtime_device = load_mms_model(
        device=device or DEFAULT_DEVICE,
        target_lang=(target_lang or DEFAULT_MMS_TARGET_LANG),
        model_id=(model_id or DEFAULT_MMS_MODEL_ID),
    )
    return {
        "backend": "mms",
        "device": runtime_device,
        "model_id": model_id or DEFAULT_MMS_MODEL_ID,
        "target_lang": target_lang or DEFAULT_MMS_TARGET_LANG,
    }


@app.on_event("startup")
def preload_models() -> None:
    if not PRELOAD_MODELS:
        return
    selected_backends = _selected_preload_backends()
    if "whisper" in selected_backends:
        try:
            _warm_backend(
                "whisper",
                device=DEFAULT_DEVICE,
                model_id=DEFAULT_WHISPER_MODEL_ID,
                compute_type=DEFAULT_WHISPER_COMPUTE_TYPE,
            )
        except Exception:
            pass
    if "mms" in selected_backends:
        try:
            _warm_backend(
                "mms",
                device=DEFAULT_DEVICE,
                model_id=DEFAULT_MMS_MODEL_ID,
                target_lang=DEFAULT_MMS_TARGET_LANG,
            )
        except Exception:
            pass
    if "omni" in selected_backends:
        try:
            _warm_backend(
                "omni",
                device=DEFAULT_DEVICE,
                model_id=DEFAULT_OMNI_MODEL_ID,
                target_lang=DEFAULT_OMNI_TARGET_LANG,
            )
        except Exception:
            pass


@app.post("/warm")
def warm_backend(
    backend: str = Form(DEFAULT_BACKEND),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str | None = Form(default=None),
    target_lang: str | None = Form(default=None),
    compute_type: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    warmed = _warm_backend(
        backend,
        device=device,
        model_id=model_id,
        compute_type=compute_type,
        target_lang=target_lang,
    )
    return {
        "ok": True,
        "warmed": warmed,
        "runtime": {
            "mms": probe_mms_runtime(),
            "omni": probe_omni_runtime(),
            "whisper": probe_whisper_runtime(),
        },
    }


def _normalized_backend(value: str | None) -> str:
    backend = (value or DEFAULT_BACKEND or "whisper").strip().lower()
    if backend not in {"whisper", "mms", "omni"}:
        raise HTTPException(status_code=400, detail="backend must be 'whisper', 'mms', or 'omni'.")
    return backend


def _temp_file(upload: UploadFile, content: bytes) -> str:
    suffix = Path(upload.filename or "upload.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name


def _transcribe(
    *,
    upload: UploadFile,
    content: bytes,
    backend: str,
    device: str,
    model_id: str | None,
    language: str | None,
    target_lang: str | None,
    task: str | None,
    compute_type: str | None,
    beam_size: int | None,
    chunk_seconds: int | None,
    batch_size: int | None,
):
    tmp_path = _temp_file(upload, content)
    try:
        if backend == "whisper":
            result = transcribe_whisper_file(
                tmp_path,
                device=device or DEFAULT_DEVICE,
                model_id=(model_id or DEFAULT_WHISPER_MODEL_ID),
                language=(language or DEFAULT_WHISPER_LANGUAGE or None),
                task=(task or DEFAULT_WHISPER_TASK or "transcribe"),
                compute_type=(compute_type or DEFAULT_WHISPER_COMPUTE_TYPE or "auto"),
                beam_size=beam_size if beam_size is not None else DEFAULT_WHISPER_BEAM_SIZE,
            )
            return JSONResponse(
                {
                    "ok": True,
                    "backend": "whisper",
                    "transcript": result.text,
                    "model_id": result.model_id,
                    "device": result.device,
                    "compute_type": result.compute_type,
                    "language": result.language,
                    "task": result.task,
                    "audio_seconds": result.audio_seconds,
                    "segment_count": result.segment_count,
                    "preprocessing_ms": result.preprocessing_ms,
                    "inference_ms": result.inference_ms,
                    "total_ms": result.total_ms,
                    "realtime_factor": result.realtime_factor,
                }
            )

        if backend == "omni":
            result = transcribe_omni_file(
                tmp_path,
                device=device or DEFAULT_DEVICE,
                model_id=(model_id or DEFAULT_OMNI_MODEL_ID),
                target_lang=(target_lang or DEFAULT_OMNI_TARGET_LANG),
                chunk_seconds=chunk_seconds if chunk_seconds is not None else DEFAULT_OMNI_CHUNK_SECONDS,
                batch_size=batch_size if batch_size is not None else DEFAULT_OMNI_BATCH_SIZE,
            )
            return JSONResponse(
                {
                    "ok": True,
                    "backend": "omni",
                    "transcript": result.text,
                    "model_id": result.model_id,
                    "device": result.device,
                    "target_lang": result.target_lang,
                    "audio_seconds": result.audio_seconds,
                    "chunk_count": result.chunk_count,
                    "sample_rate": result.sample_rate,
                    "load_ms": result.load_ms,
                    "preprocessing_ms": result.preprocessing_ms,
                    "inference_ms": result.inference_ms,
                    "total_ms": result.total_ms,
                    "realtime_factor": result.realtime_factor,
                }
            )

        result = transcribe_mms_file(
            tmp_path,
            device=device or DEFAULT_DEVICE,
            target_lang=(target_lang or DEFAULT_MMS_TARGET_LANG),
            model_id=(model_id or DEFAULT_MMS_MODEL_ID),
            chunk_seconds=chunk_seconds if chunk_seconds is not None else DEFAULT_MMS_CHUNK_SECONDS,
            batch_size=batch_size if batch_size is not None else DEFAULT_MMS_BATCH_SIZE,
        )
        return JSONResponse(
            {
                "ok": True,
                "backend": "mms",
                "transcript": result.text,
                "model_id": result.model_id,
                "device": result.device,
                "target_lang": result.target_lang,
                "audio_seconds": result.audio_seconds,
                "chunk_count": result.chunk_count,
                "sample_rate": result.sample_rate,
                "preprocessing_ms": result.preprocessing_ms,
                "inference_ms": result.inference_ms,
                "total_ms": result.total_ms,
                "realtime_factor": result.realtime_factor,
            }
        )
    except (MMSDependencyError, OmniDependencyError, WhisperDependencyError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/transcribe/file")
async def transcribe_file(
    file: UploadFile = File(...),
    backend: str = Form(DEFAULT_BACKEND),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str | None = Form(default=None),
    language: str | None = Form(default=None),
    target_lang: str | None = Form(default=None),
    task: str | None = Form(default=None),
    compute_type: str | None = Form(default=None),
    beam_size: int | None = Form(default=None),
    chunk_seconds: int | None = Form(default=None),
    batch_size: int | None = Form(default=None),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(content) > DEFAULT_MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {DEFAULT_MAX_FILE_MB} MB limit.")

    return _transcribe(
        upload=file,
        content=content,
        backend=_normalized_backend(backend),
        device=device,
        model_id=model_id,
        language=language,
        target_lang=target_lang,
        task=task,
        compute_type=compute_type,
        beam_size=beam_size,
        chunk_seconds=chunk_seconds,
        batch_size=batch_size,
    )


@app.post("/transcribe/whisper/file")
async def transcribe_whisper(
    file: UploadFile = File(...),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str = Form(DEFAULT_WHISPER_MODEL_ID),
    language: str = Form(DEFAULT_WHISPER_LANGUAGE),
    task: str = Form(DEFAULT_WHISPER_TASK),
    compute_type: str = Form(DEFAULT_WHISPER_COMPUTE_TYPE),
    beam_size: int = Form(DEFAULT_WHISPER_BEAM_SIZE),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(content) > DEFAULT_MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {DEFAULT_MAX_FILE_MB} MB limit.")

    return _transcribe(
        upload=file,
        content=content,
        backend="whisper",
        device=device,
        model_id=model_id,
        language=language,
        target_lang=None,
        task=task,
        compute_type=compute_type,
        beam_size=beam_size,
        chunk_seconds=None,
        batch_size=None,
    )


@app.post("/transcribe/mms/file")
async def transcribe_mms(
    file: UploadFile = File(...),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str = Form(DEFAULT_MMS_MODEL_ID),
    target_lang: str = Form(DEFAULT_MMS_TARGET_LANG),
    chunk_seconds: int = Form(DEFAULT_MMS_CHUNK_SECONDS),
    batch_size: int = Form(DEFAULT_MMS_BATCH_SIZE),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(content) > DEFAULT_MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {DEFAULT_MAX_FILE_MB} MB limit.")

    return _transcribe(
        upload=file,
        content=content,
        backend="mms",
        device=device,
        model_id=model_id,
        language=None,
        target_lang=target_lang,
        task=None,
        compute_type=None,
        beam_size=None,
        chunk_seconds=chunk_seconds,
        batch_size=batch_size,
    )


@app.post("/transcribe/omni/file")
async def transcribe_omni(
    file: UploadFile = File(...),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str = Form(DEFAULT_OMNI_MODEL_ID),
    target_lang: str = Form(DEFAULT_OMNI_TARGET_LANG),
    chunk_seconds: int = Form(DEFAULT_OMNI_CHUNK_SECONDS),
    batch_size: int = Form(DEFAULT_OMNI_BATCH_SIZE),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _check_auth(authorization, x_api_key)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(content) > DEFAULT_MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {DEFAULT_MAX_FILE_MB} MB limit.")

    return _transcribe(
        upload=file,
        content=content,
        backend="omni",
        device=device,
        model_id=model_id,
        language=None,
        target_lang=target_lang,
        task=None,
        compute_type=None,
        beam_size=None,
        chunk_seconds=chunk_seconds,
        batch_size=batch_size,
    )
