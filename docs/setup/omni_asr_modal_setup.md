# Adding omniASR to the Modal Endpoint

Guide for adding a second ASR route (`/transcribe/omni/file`) alongside the existing MMS route in the WellNest Modal GPU app.

## Why

`omnilingual-asr` requires `fairseq2`, which has no Windows wheels. Modal runs Linux on GPU, so it installs cleanly there. Adding omniASR to Modal lets you benchmark it against MMS on identical hardware (same L4 GPU, same audio).

---

## 1. Update the `image` in your Modal file

```python
image = (
    modal.Image.debian_slim()
    .apt_install("libsndfile1", "ffmpeg")
    .pip_install(
        "torch==2.8.0", "torchaudio==2.8.0",
        extra_index_url="https://download.pytorch.org/whl/cu128",
    )
    .pip_install(
        "fairseq2",
        extra_index_url="https://fair.pkg.atmeta.com/fairseq2/whl/pt2.8.0/cu128",
    )
    .pip_install(
        "omnilingual-asr",
        "silero-vad",
        "jiwer",
        "fastapi",
        "python-multipart",
    )
    # Must be last — omnilingual-asr pulls numpy 1.x as a dep; torch 2.8 needs numpy 2.x
    .pip_install("numpy>=2.0,<2.3", extra_options="--upgrade --force-reinstall")
)
```

> `libsndfile1` is required by soundfile (a fairseq2 transitive dep).

---

## 2. Add helpers and the omniASR route

Paste this into your Modal app file. Put `_vad_chunk` and `_get_omni_pipeline` **before** `transcribe_omni`.

```python
import os, torch, tempfile, wave as _wave
import numpy as np
import torchaudio, torchaudio.functional as TAF

# ── helpers ───────────────────────────────────────────────────────────────────

def _vad_chunk(audio, max_chunk_seconds=30):
    """Split at silence boundaries using silero-VAD; fall back to fixed splits."""
    max_samples = max_chunk_seconds * 16000
    if len(audio) <= max_samples:
        return [audio]
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad
        vad = load_silero_vad()
        tensor = torch.from_numpy(audio).float()
        timestamps = get_speech_timestamps(tensor, vad, sampling_rate=16000)
        if timestamps:
            chunks, chunk_start, last_end = [], 0, 0
            for seg in timestamps:
                if int(seg["end"]) - chunk_start > max_samples and last_end > chunk_start:
                    chunks.append(audio[chunk_start:last_end])
                    chunk_start = int(seg["start"])
                last_end = int(seg["end"])
            if chunk_start < len(audio):
                chunks.append(audio[chunk_start:])
            if chunks:
                return chunks
    except Exception:
        pass
    return [audio[i:i + max_samples] for i in range(0, len(audio), max_samples)]


def _init_gang(device):
    """Required by fairseq2 CTC pipeline before each inference call."""
    from fairseq2.gang import create_fake_gangs, _thread_local
    _thread_local.current_gangs = [create_fake_gangs(torch.device(device))]


# Module-level cache — survives warm container reuse
_OMNI_PIPELINE = None

def _get_omni_pipeline(model_card: str = "omniASR_CTC_1B"):
    global _OMNI_PIPELINE
    if _OMNI_PIPELINE is None:
        from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _init_gang(device)
        _OMNI_PIPELINE = ASRInferencePipeline(model_card=model_card, device=device)
    return _OMNI_PIPELINE


# ── endpoint ──────────────────────────────────────────────────────────────────

@app.function(gpu="L4", image=image, timeout=300)
@modal.web_endpoint(method="POST")
async def transcribe_omni(request: Request):
    import time

    form = await request.form()
    audio_file = form["file"]
    target_lang = form.get("target_lang", "jam_Latn")

    audio_bytes = await audio_file.read()

    suffix = "." + (audio_file.filename.rsplit(".", 1)[-1] if "." in audio_file.filename else "webm")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_in = f.name

    waveform, orig_sr = torchaudio.load(tmp_in)
    if orig_sr != 16000:
        waveform = TAF.resample(waveform, orig_sr, 16000)
    audio = waveform.mean(0).numpy()
    audio_seconds = len(audio) / 16000

    chunks = _vad_chunk(audio, max_chunk_seconds=30)

    tmp_paths = []
    for chunk in chunks:
        audio_int16 = (chunk * 32767).clip(-32768, 32767).astype(np.int16)
        tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tf.close()
        with _wave.open(tf.name, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(16000); wf.writeframes(audio_int16.tobytes())
        tmp_paths.append(tf.name)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    _init_gang(device)  # re-init per request — required for fairseq2 thread safety
    pipeline = _get_omni_pipeline()

    t0 = time.perf_counter()
    # transcribe() silently drops results after the first when given multiple paths —
    # call once per chunk to get complete output
    transcriptions = []
    for path in tmp_paths:
        transcriptions.extend(list(pipeline.transcribe([path], lang=[target_lang], batch_size=1)))
    inference_ms = int((time.perf_counter() - t0) * 1000)

    for p in tmp_paths:
        os.unlink(p)
    os.unlink(tmp_in)

    text = " ".join(t.strip() for t in transcriptions if t.strip())
    rtf = round(inference_ms / 1000 / audio_seconds, 4) if audio_seconds > 0 else None

    return {
        "ok": True,
        "transcript": text,
        "audio_seconds": round(audio_seconds, 3),
        "chunk_count": len(chunks),
        "inference_ms": inference_ms,
        "realtime_factor": rtf,
        "model_card": "omniASR_CTC_1B",
        "target_lang": target_lang,
    }
```

---

## 3. Add the URL to WellNest `.env`

```
MODAL_OMNI_URL=https://your-workspace--wellnest-speech-api-transcribe-omni.modal.run
```

> Get the URL from `modal deploy` output or the Modal dashboard.

---

## 4. Add `MODAL_OMNI_URL` to Django settings

In `wellnest/settings.py` after `MODAL_MMS_URL`:

```python
MODAL_OMNI_URL = config("MODAL_OMNI_URL", default="")
```

---

## 5. Wire it into `triage.py`

Add a `transcribe_modal_omni()` function mirroring `transcribe_modal_mms()`:

```python
def transcribe_modal_omni(audio_path, *, target_lang="jam_Latn", batch_size=4) -> dict:
    url = settings.MODAL_OMNI_URL
    if not url:
        raise TriageDependencyError("MODAL_OMNI_URL not set in .env")
    headers = {}
    if settings.MODAL_MMS_API_KEY:
        headers["X-API-Key"] = settings.MODAL_MMS_API_KEY

    src = Path(audio_path)
    tmp_wav = _convert_webm_to_wav(src) if src.suffix.lower() in {".webm", ".ogg", ".opus"} else None
    send_path = tmp_wav or src
    try:
        with open(send_path, "rb") as f:
            resp = requests.post(
                url, headers=headers,
                files={"file": (send_path.name, f, "audio/wav" if tmp_wav else "audio/webm")},
                data={"target_lang": target_lang, "batch_size": str(batch_size)},
                timeout=300,
            )
    finally:
        if tmp_wav:
            tmp_wav.unlink(missing_ok=True)

    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Modal omniASR error: {data}")
    return {
        "text": data["transcript"],
        "model_card": data.get("model_card", "omniASR_CTC_1B"),
        "audio_seconds": data.get("audio_seconds"),
        "chunk_count": data.get("chunk_count"),
        "inference_ms": data.get("inference_ms"),
        "realtime_factor": data.get("realtime_factor"),
        "device": "cuda",
        "target_lang": target_lang,
    }
```

---

## 6. Deploy

```bash
modal deploy your_modal_app.py
```

First cold start downloads ~3.7 GB of model weights and builds the image (~5 min). Subsequent calls reuse the cached container — warm inference on L4 is ~0.07x RTF.

---

## Language codes

| Language | Code |
|---|---|
| Jamaican Creole (Patois) | `jam_Latn` |
| English | `eng_Latn` |
| Spanish | `spa_Latn` |
| French | `fra_Latn` |
| Haitian Creole | `hat_Latn` |

Full list: `from omnilingual_asr.models.wav2vec2_llama.lang_ids import supported_langs`
