"""Modal wrapper for OmniASR transcription on a T4 with scale-to-zero defaults."""

from __future__ import annotations

import os
from pathlib import Path

import modal


APP_DIR = Path(__file__).resolve().parent
CACHE_ROOT = Path("/opt/omni-cache")
RUNTIME_SECRET_NAME = (
    os.getenv("MODAL_RUNTIME_SECRET_NAME", "").strip()
    or os.getenv("MODAL_SPEECH_SECRET_NAME", "").strip()
    or os.getenv("MODAL_HF_SECRET_NAME", "").strip()
    or "wellnest-speech-runtime"
)
SECRETS = [modal.Secret.from_name(RUNTIME_SECRET_NAME)]
BAKE_OMNI_MODEL = os.getenv("MODAL_OMNI_BAKE_MODEL", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "libsndfile1", "curl", "ca-certificates", "build-essential")
    .env(
        {
            "HF_HOME": str(CACHE_ROOT / "huggingface"),
            "TRANSFORMERS_CACHE": str(CACHE_ROOT / "huggingface"),
            "XDG_CACHE_HOME": str(CACHE_ROOT / "xdg-cache"),
            "FAIRSEQ2_CACHE_DIR": str(CACHE_ROOT / "fairseq2"),
            "TORCH_HOME": str(CACHE_ROOT / "torch"),
            "HF_XET_HIGH_PERFORMANCE": "1",
            "PYTHONUNBUFFERED": "1",
            "LIGHTNING_SPEECH_DEVICE": "auto",
            "LIGHTNING_SPEECH_BACKEND": "omni",
            "LIGHTNING_OMNI_MODEL_ID": "omniASR_CTC_1B_v2",
            "LIGHTNING_OMNI_TARGET_LANG": "jam_Latn",
            "LIGHTNING_OMNI_CHUNK_SECONDS": "30",
            "LIGHTNING_OMNI_BATCH_SIZE": "1",
            "LIGHTNING_PRELOAD_MODELS": "false",
            "LIGHTNING_PRELOAD_BACKENDS": "",
            "PORT": "8000",
        }
    )
    .run_commands(
        "python -m pip install --upgrade pip",
        "python -m pip install torch==2.8.0 torchaudio==2.8.0 --extra-index-url https://download.pytorch.org/whl/cu128",
        "python -m pip install 'fairseq2<=0.6.0' --extra-index-url https://fair.pkg.atmeta.com/fairseq2/whl/pt2.8.0/cu128",
        "python -m pip install fastapi==0.116.1 uvicorn==0.35.0 python-multipart==0.0.20 requests==2.33.1 omnilingual-asr==0.2.0 silero-vad jiwer",
        "python -c \"import fastapi, omnilingual_asr; print(fastapi.__version__)\"",
    )
    .workdir("/app")
    .add_local_dir(APP_DIR, remote_path="/app", copy=True)
)

if BAKE_OMNI_MODEL:
    image = image.run_commands(
        f"mkdir -p {CACHE_ROOT}/huggingface {CACHE_ROOT}/xdg-cache {CACHE_ROOT}/fairseq2 {CACHE_ROOT}/torch",
        "python -c \"from omni_asr import load_omni_pipeline; pipeline, device, load_ms = load_omni_pipeline(device='cpu', model_id='omniASR_CTC_1B_v2'); print(f'Omni model cached in image on {device} in {load_ms} ms')\"",
    )

app = modal.App("wellnest-speech-api-modal-omni")


@app.function(
    image=image,
    gpu="T4",
    secrets=SECRETS,
    timeout=60 * 20,
    startup_timeout=60 * 20,
    # Scale-to-zero stays enabled; the deploy-side speed win comes from baking
    # the Omni weights into the image instead of keeping warm containers around.
    min_containers=int(os.getenv("MODAL_OMNI_MIN_CONTAINERS", "0")),
    buffer_containers=int(os.getenv("MODAL_OMNI_BUFFER_CONTAINERS", "0")),
    max_containers=int(os.getenv("MODAL_OMNI_MAX_CONTAINERS", "10")),
    scaledown_window=int(os.getenv("MODAL_OMNI_SCALEDOWN_WINDOW", "30")),
)
@modal.asgi_app()
def fastapi_app_omni():
    from app import app as api

    return api
