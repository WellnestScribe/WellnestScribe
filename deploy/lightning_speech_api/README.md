# WellNest Speech API

This folder is a **portable GPU speech service** that serves both:

- **Whisper** via `faster-whisper`
- **MMS** via `facebook/mms-1b-l1107`

The main route defaults to **Whisper**, while MMS stays available for side by
side testing.

The goal is to keep **one codebase** that can move across:

- local Docker
- Runpod
- Modal
- notebook-style GPU environments

## Folder contents

- `app.py`: FastAPI app
- `whisper_asr.py`: Whisper runtime
- `mms_asr.py`: MMS runtime
- `Dockerfile`: portable GPU container
- `.dockerignore`: smaller build context
- `run.py`: local/container launcher
- `start.sh`: small shell launcher
- `test_client.py`: local request tester
- `modal_app.py`: Modal wrapper
- `requirements.txt`: Python dependencies

## API routes

- `GET /health`
- `POST /transcribe/file`
- `POST /transcribe/whisper/file`
- `POST /transcribe/mms/file`

`/transcribe/file` accepts `backend=whisper` or `backend=mms`.

## Recommended default

Use **Whisper** as the main production path:

- better general English transcription
- cleaner fit for broader clinical dictation
- easier to compare across providers

Keep **MMS** as a comparison route for Jamaican Patois-heavy audio.

## Environment variables

Common:

```env
LIGHTNING_SPEECH_API_TOKEN=replace-me
LIGHTNING_SPEECH_BACKEND=whisper
LIGHTNING_SPEECH_DEVICE=auto
LIGHTNING_SPEECH_MAX_FILE_MB=100
LIGHTNING_PRELOAD_MODELS=false
LIGHTNING_PRELOAD_BACKENDS=
PORT=8000
```

If `LIGHTNING_PRELOAD_MODELS=true`, the service now preloads only the backend in
`LIGHTNING_SPEECH_BACKEND` by default. You can override that with a
comma-separated list in `LIGHTNING_PRELOAD_BACKENDS`, for example:

```env
LIGHTNING_PRELOAD_MODELS=true
LIGHTNING_PRELOAD_BACKENDS=mms
```

Whisper:

```env
LIGHTNING_WHISPER_MODEL_ID=large-v3
LIGHTNING_WHISPER_LANGUAGE=en
LIGHTNING_WHISPER_TASK=transcribe
LIGHTNING_WHISPER_COMPUTE_TYPE=auto
LIGHTNING_WHISPER_BEAM_SIZE=5
```

MMS:

```env
LIGHTNING_MMS_MODEL_ID=facebook/mms-1b-l1107
LIGHTNING_MMS_TARGET_LANG=jam
LIGHTNING_MMS_CHUNK_SECONDS=25
```

## Local Docker

Build:

```bash
docker build -t wellnest-speech-api .
```

Run with GPU:

```bash
docker run --rm -it \
  --gpus all \
  -p 8000:8000 \
  -e LIGHTNING_SPEECH_API_TOKEN=replace-me \
  -e LIGHTNING_SPEECH_BACKEND=whisper \
  -e LIGHTNING_PRELOAD_MODELS=true \
  wellnest-speech-api
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Whisper test:

```bash
python test_client.py \
  --url http://127.0.0.1:8000/transcribe/file \
  --file /path/to/sample.webm \
  --token replace-me
```

MMS test:

```bash
python test_client.py \
  --url http://127.0.0.1:8000/transcribe/file \
  --file /path/to/sample.webm \
  --token replace-me \
  --backend mms \
  --model-id facebook/mms-1b-l1107 \
  --target-lang jam
```

## Runpod advice

Runpod is a good fit for this folder because Runpod supports **custom
containers** for serverless endpoints and API workers ([Runpod Serverless overview](https://docs.runpod.io/serverless/endpoints/overview)).

Best practical path on Runpod:

1. Build this Docker image locally.
2. Push it to Docker Hub or GHCR.
3. Point a Runpod endpoint or pod at that image.
4. Set the env vars above in Runpod.
5. Hit `/health` until the model is warm.

For cheaper experimentation:

- use a **pod** first if you want a traditional API server
- use **serverless** later if cold starts and model downloads are acceptable

If you use Runpod serverless, remember:

- cold starts matter
- model downloads matter
- preloading both models may increase startup time

So for Runpod serverless, I would start with:

- `LIGHTNING_SPEECH_BACKEND=whisper`
- `LIGHTNING_PRELOAD_MODELS=false`

and only load MMS when you need it.

## Modal advice

Modal can use a Dockerfile-backed image, and Modal’s docs support using an
existing Dockerfile as an image source ([existing images](https://modal.com/docs/guide/existing-images), [GPU guide](https://modal.com/docs/guide/gpu)).

This folder includes `modal_app.py` so you can deploy the same service without
rewriting the FastAPI app.

### One-time local setup

Install Modal locally:

```bash
pip install modal
modal setup
```

Create the secret:

```bash
modal secret create wellnest-speech-api \
  LIGHTNING_SPEECH_API_TOKEN=replace-me
```

### Deploy to Modal

From inside this folder:

```bash
modal deploy modal_app.py
```

That deploys the FastAPI app with a T4 GPU.

During development you can also run:

```bash
modal serve modal_app.py
```

### Important Modal note

Modal is usually better used with its **native app model** than by treating it
like a generic Docker host. The wrapper here is the bridge: one Dockerfile, but
still deployed in a Modal-friendly way.

## Why one Docker image is a good idea

Yes, this is a good direction.

Benefits:

- one runtime definition
- fewer environment-specific surprises
- easier to benchmark across providers
- easier to move from testing to production-style hosting

## What I would do in your position

If the goal is **cheap testing now** and **future portability**:

1. Keep this folder as the canonical speech API.
2. Use Docker as the base packaging format.
3. Test on Modal and Runpod from the same folder.
4. Default the app to Whisper.
5. Keep MMS as a comparison path, not the main production path.

## What I would not do

I would not build separate one-off notebook environments for every provider
unless the provider forces it. That gets messy fast.

I also would not preload both models everywhere by default unless:

- you really need both warm at all times
- you have enough memory headroom
- you are okay with longer cold starts

## Suggested app-side `.env`

For your Django app:

```env
SCRIBE_USE_REAL_AI=True
SCRIBE_TRANSCRIPTION_BACKEND=lightning
SCRIBE_LIGHTNING_TRANSCRIBE_URL=https://YOUR-URL/transcribe/file
SCRIBE_LIGHTNING_TRANSCRIBE_TOKEN=replace-me
SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE=whisper
SCRIBE_LIGHTNING_TRANSCRIBE_LANGUAGE=en
SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE=auto
SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID=large-v3
SCRIBE_LIGHTNING_TRANSCRIBE_TASK=transcribe
SCRIBE_LIGHTNING_TRANSCRIBE_COMPUTE_TYPE=auto
SCRIBE_LIGHTNING_TRANSCRIBE_BEAM_SIZE=5
SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG=jam
SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS=25
SCRIBE_LIGHTNING_TRANSCRIBE_TIMEOUT=600
```

If you want to switch the same endpoint back to MMS later:

```env
SCRIBE_LIGHTNING_TRANSCRIBE_ENGINE=mms
SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID=facebook/mms-1b-l1107
```
