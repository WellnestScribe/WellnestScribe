"""Modal-native wrapper for the portable speech API."""

from __future__ import annotations

from pathlib import Path

import modal


APP_DIR = Path(__file__).resolve().parent

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

app = modal.App("wellnest-speech-api-modal-v2")


@app.function(
    image=image,
    gpu="T4",
    timeout=60 * 20,
    # Keep the GPU warm only briefly during testing to reduce idle spend.
    scaledown_window=30,
)
@modal.asgi_app()
def fastapi_app_v2():
    from app import app as api

    return api
