"""Modal wrapper for the portable speech API on an A100."""

from __future__ import annotations

import os
from pathlib import Path

import modal


APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path("/models")
CACHE_VOLUME = modal.Volume.from_name(
    os.getenv("MODAL_HF_CACHE_VOLUME", "wellnest-speech-hf-cache"),
    create_if_missing=True,
)
RUNTIME_SECRET_NAME = (
    os.getenv("MODAL_RUNTIME_SECRET_NAME", "").strip()
    or os.getenv("MODAL_SPEECH_SECRET_NAME", "").strip()
    or os.getenv("MODAL_HF_SECRET_NAME", "").strip()
    or "wellnest-speech-runtime"
)
SECRETS = [modal.Secret.from_name(RUNTIME_SECRET_NAME)]

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04",
        add_python="3.10",
    )
    .entrypoint([])
    .apt_install("ffmpeg", "git", "curl", "ca-certificates", "build-essential")
    .env(
        {
            "HF_HOME": "/models/huggingface",
            "TRANSFORMERS_CACHE": "/models/huggingface",
            "XDG_CACHE_HOME": "/models/cache",
            "HF_XET_HIGH_PERFORMANCE": "1",
            "LD_LIBRARY_PATH": "/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64",
            "LIGHTNING_SPEECH_DEVICE": "auto",
            "LIGHTNING_SPEECH_BACKEND": "whisper",
            "PORT": "8000",
        }
    )
    .pip_install_from_requirements(str(APP_DIR / "requirements.txt"))
    .run_commands('python -c "import fastapi, uvicorn; print(fastapi.__version__)"')
    .workdir("/app")
    .add_local_dir(APP_DIR, remote_path="/app", copy=True)
)

app = modal.App("wellnest-speech-api-modal-a100")


@app.function(
    image=image,
    gpu="A100",
    secrets=SECRETS,
    volumes={MODEL_DIR.as_posix(): CACHE_VOLUME},
    timeout=60 * 20,
    startup_timeout=60 * 10,
    max_containers=int(os.getenv("MODAL_A100_MAX_CONTAINERS", "1")),
    # Keep the GPU warm only briefly during testing to reduce idle spend.
    scaledown_window=int(os.getenv("MODAL_A100_SCALEDOWN_WINDOW", "30")),
)
@modal.asgi_app()
def fastapi_app_a100():
    from app import app as api

    return api
