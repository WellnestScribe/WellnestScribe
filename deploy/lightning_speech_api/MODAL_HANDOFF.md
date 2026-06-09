# Modal MMS Handoff

This is the smallest clean handoff for someone who needs to run the
transcription API on Modal and tune it for speed.

## What to send

Do **not** send only `app.py`.

Send this whole folder:

- `app.py`
- `mms_asr.py`
- `whisper_asr.py`
- `requirements.txt`
- `modal_app.py`
- `modal_app_mms.py`
- `modal_app_a100.py`
- `Dockerfile`
- `run.py`
- `README.md`

If the goal is **T4 + MMS only**, the minimum files they need to understand are:

- `app.py`
- `mms_asr.py`
- `requirements.txt`
- `modal_app_mms.py`

## What each file does

- `app.py`: FastAPI routes and request handling
- `mms_asr.py`: MMS model loading, audio decode/resample, chunking, inference
- `requirements.txt`: Python dependencies
- `modal_app.py`: Modal deployment wrapper for a T4 GPU
- `modal_app_mms.py`: Modal deployment wrapper tuned for MMS on a T4
- `modal_app_a100.py`: Modal deployment wrapper for an A100 GPU
- `Dockerfile`: portable container for non-Modal hosts

## What your friend needs to know

There are 3 separate concerns:

1. Build and deploy the API to Modal
2. Configure the Modal autoscaler for cost vs speed
3. Call the API correctly from the app

## Basic Modal deploy

From inside this folder:

```bash
pip install modal
modal setup
modal deploy modal_app.py --stream-logs
```

That deploys the general-purpose FastAPI app on a **T4**.

For the fast MMS/T4 path:

```bash
modal deploy modal_app_mms.py --stream-logs
```

If they want the A100 test version instead:

```bash
modal deploy modal_app_a100.py --stream-logs
```

## Current API shape

Routes:

- `GET /health`
- `POST /warm`
- `POST /transcribe/file`
- `POST /transcribe/whisper/file`
- `POST /transcribe/mms/file`

For MMS production use, prefer:

- `POST /transcribe/mms/file`

That avoids the generic backend switch and makes intent explicit.

## Curl examples

Health:

```bash
curl "https://YOUR-MODAL-URL/health" \
  -H "X-API-Key: YOUR_TOKEN"
```

MMS direct route:

```bash
curl -X POST "https://YOUR-MODAL-URL/transcribe/mms/file" \
  -H "X-API-Key: YOUR_TOKEN" \
  -F "file=@/path/to/audio.wav" \
  -F "target_lang=jam"
```

Generic route using MMS:

```bash
curl -X POST "https://YOUR-MODAL-URL/transcribe/file" \
  -H "X-API-Key: YOUR_TOKEN" \
  -F "file=@/path/to/audio.wav" \
  -F "backend=mms" \
  -F "target_lang=jam"
```

If auth is enabled:

```bash
curl -X POST "https://YOUR-MODAL-URL/transcribe/mms/file" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/audio.wav" \
  -F "target_lang=jam"
```

Warm the MMS model before the first clinic request:

```bash
curl -X POST "https://YOUR-MODAL-URL/warm" \
  -H "X-API-Key: YOUR_TOKEN" \
  -F "backend=mms"
```

## Best speed settings for MMS on T4

If the goal is "fast enough for multiple doctors" on Modal, the most useful
settings are:

- `LIGHTNING_SPEECH_BACKEND=mms`
- `LIGHTNING_PRELOAD_MODELS=true`
- `LIGHTNING_PRELOAD_BACKENDS=mms`
- `LIGHTNING_MMS_TARGET_LANG=jam`
- `LIGHTNING_MMS_CHUNK_SECONDS=25` to start, then benchmark `35`, `45`, `60`
- `LIGHTNING_MMS_BATCH_SIZE=4` to start, then benchmark `6` and `8`

Why:

- `LIGHTNING_PRELOAD_MODELS=true` loads the model at container startup instead
  of making the first doctor wait for it
- keeping MMS as the default avoids unnecessary ambiguity in the serving path

## Modal autoscaler knobs that matter

These are not in `app.py`. They are part of the Modal wrapper.

The important settings are:

- `min_containers`
- `buffer_containers`
- `max_containers`
- `scaledown_window`

What they mean:

- `min_containers=0`: scale to zero when idle and stop burning credits
- `buffer_containers=0`: do not hold extra warm workers by default
- `max_containers=3` or `4`: allow multiple doctors to transcribe in parallel
- `scaledown_window=30`: drop idle workers quickly by default

## Recommended default T4 profile

Use this logic if cost control is the priority:

- no always-warm T4
- preload MMS
- allow 2 to 4 T4 containers total under load

That gives:

- much lower idle spend
- no silent GPU drain when nobody is using the API
- parallel handling for multiple doctors

## Optional fast clinic-hours profile

Only opt into this when you knowingly want to pay for faster first requests:

- `min_containers=1`
- `buffer_containers=1`
- `scaledown_window=300`
- preload MMS

That is faster, but it will keep costing money while the GPU is warm.

## Why requests feel slow today

The MMS pipeline is not spending most of its time on the GPU itself.

The work is:

1. receive uploaded file
2. write temp file
3. decode audio
4. resample audio
5. split into chunks
6. run chunks on the GPU
7. stitch output text

So the main speed bottlenecks are often:

- cold container startup
- model loading
- audio decode/resample
- chunking overhead

Not just "GPU is too weak."

## Biggest speed wins

Order of impact:

1. Keep one T4 warm during active hours only if the business is okay with the cost
2. Preload the MMS model
3. Upload already-normalized audio
4. Use a dedicated MMS deployment
5. Scale across multiple T4 containers for multiple doctors

## Audio upload advice

If the client uploads:

- mono audio
- 16 kHz
- WAV / PCM
- trimmed silence

the API does less work and becomes noticeably faster.

Example pre-convert before upload:

```bash
ffmpeg -i input.mpeg -ac 1 -ar 16000 -c:a pcm_s16le output_16k.wav
```

Then send `output_16k.wav` to the MMS endpoint.

## Multiple doctors

Do not think of "one GPU doing everything at once" as the first answer.

The safer first design is:

- one request per container
- Modal scales to more T4 containers as traffic increases

This is simpler and gives more predictable latency.

Suggested first limit:

- `max_containers=3`

Then raise if demand proves it is needed.

## Hugging Face token

Use one Modal secret for both the speech API token and the optional
Hugging Face token:

```bash
modal secret create wellnest-speech-runtime \
  LIGHTNING_SPEECH_API_TOKEN=replace-me \
  HF_TOKEN=replace-me-if-you-have-one

export MODAL_RUNTIME_SECRET_NAME=wellnest-speech-runtime
```

If they see warnings about unauthenticated HF Hub requests, set `HF_TOKEN`.

Why:

- improves model download reliability
- helps cold starts
- does **not** change the raw speed of already-loaded GPU inference much

It mostly helps the first container startup and cache misses.

## What not to optimize first

Do not jump straight to:

- A100
- same-container heavy concurrency
- region pinning

until the team has already tested:

- warm T4
- preload
- normalized audio
- dedicated MMS endpoint

Those are usually the higher-value changes first.

## What to ask your friend to report back

Have them benchmark and report:

- cold request total time
- warm request total time
- `preprocessing_ms`
- `inference_ms`
- `total_ms`
- concurrency behavior with 2 simultaneous uploads
- concurrency behavior with 3 simultaneous uploads

That gives enough data to decide whether to tune chunk size, keep more warm
containers, or move to a bigger GPU.
