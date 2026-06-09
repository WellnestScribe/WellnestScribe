"""FastAPI service for running MMS transcription on a Lightning AI GPU."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from mms_asr import (
    MMSDependencyError,
    probe_mms_runtime,
    transcribe_mms_file,
)


APP_TITLE = "WellNest Lightning MMS API"
DEFAULT_MODEL_ID = os.getenv("LIGHTNING_MMS_MODEL_ID", "facebook/mms-1b-l1107")
DEFAULT_TARGET_LANG = os.getenv("LIGHTNING_MMS_TARGET_LANG", "jam")
DEFAULT_DEVICE = os.getenv("LIGHTNING_MMS_DEVICE", "auto")
DEFAULT_CHUNK_SECONDS = int(os.getenv("LIGHTNING_MMS_CHUNK_SECONDS", "25"))
API_TOKEN = os.getenv("LIGHTNING_MMS_API_TOKEN", "").strip()
MAX_FILE_MB = int(os.getenv("LIGHTNING_MMS_MAX_FILE_MB", "100"))

app = FastAPI(title=APP_TITLE, version="0.1.0")


def _check_auth(authorization: str | None) -> None:
    if not API_TOKEN:
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
def root():
    return {
        "ok": True,
        "service": APP_TITLE,
        "endpoints": ["/health", "/transcribe/file"],
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": APP_TITLE,
        "default_model_id": DEFAULT_MODEL_ID,
        "default_target_lang": DEFAULT_TARGET_LANG,
        "default_device": DEFAULT_DEVICE,
        "runtime": probe_mms_runtime(),
    }


@app.post("/transcribe/file")
async def transcribe_file(
    file: UploadFile = File(...),
    target_lang: str = Form(DEFAULT_TARGET_LANG),
    device: str = Form(DEFAULT_DEVICE),
    model_id: str = Form(DEFAULT_MODEL_ID),
    chunk_seconds: int = Form(DEFAULT_CHUNK_SECONDS),
    authorization: str | None = Header(default=None),
):
    _check_auth(authorization)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_MB} MB limit.")

    suffix = Path(file.filename or "upload.webm").suffix or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        result = transcribe_mms_file(
            tmp_path,
            device=device,
            target_lang=target_lang,
            model_id=model_id,
            chunk_seconds=chunk_seconds,
        )
    except MMSDependencyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return JSONResponse(
        {
            "ok": True,
            "backend": "lightning_mms",
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
