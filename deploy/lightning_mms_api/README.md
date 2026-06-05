# Lightning MMS API Upload Folder

This folder is now fully standalone. You do **not** need to clone your repo on
Lightning AI and you do **not** need to give Lightning access to your Django
source code.

You can upload just the contents of this folder into a Lightning Studio and run
the MMS model there on the GPU.

Files in this folder:

- `app.py`: FastAPI server
- `mms_asr.py`: standalone MMS GPU inference logic
- `run.py`: launcher
- `requirements.txt`: Python deps
- `test_client.py`: local machine tester
- `start.sh`: tiny launcher for Linux shells

## Official Lightning references

Lightning’s own docs say Studios can take code by dragging and dropping local
files, and public ports can be exposed from the Studio UI:

- [Lightning Studios](https://lightning.ai/docs/pytorch/latest/clouds/lightning_ai.html)
- [Public ports in AI Studio](https://lightning.ai/docs/overview/ai-studio/deploy-on-public-ports)

## What to upload

Upload the **contents of this folder** into your Lightning Studio:

- `app.py`
- `mms_asr.py`
- `run.py`
- `requirements.txt`
- `start.sh`

You can upload `test_client.py` too, but that file is mainly for your local
machine.

## Lightning Studio setup

1. Create or open your Lightning Studio.
2. Choose your T4 GPU machine.
3. Drag and drop the files from this folder into the Studio file browser.
4. Open the Studio terminal.
5. Move into the folder where the files landed.

Example:

```bash
cd lightning_mms_api
```

## Install dependencies

Start with:

```bash
pip install -r requirements.txt
```

If the Studio image does not already have the right CUDA-enabled torch build,
install the matching PyTorch wheel for that environment before retrying the
requirements install.

## Start the API

Set a token first so only you can call it:

```bash
export LIGHTNING_MMS_API_TOKEN="replace-me"
export LIGHTNING_MMS_DEVICE="auto"
export LIGHTNING_MMS_TARGET_LANG="jam"
python run.py
```

Or:

```bash
bash start.sh
```

The API listens on port `8000`.

## Expose the API

In the Lightning Studio UI:

1. Expose port `8000` as a public port.
2. Copy the generated public URL.

Your endpoint will be:

```text
https://YOUR-LIGHTNING-URL/transcribe/file
```

Health check:

```bash
curl https://YOUR-LIGHTNING-URL/health
```

## Test it directly from your local machine

From your laptop or desktop:

```bash
python deploy/lightning_mms_api/test_client.py \
  --url https://YOUR-LIGHTNING-URL/transcribe/file \
  --file path/to/sample.webm \
  --token replace-me
```

That prints:

- backend
- device
- total milliseconds
- realtime factor
- transcript

## Test it with curl from your local machine

```bash
curl -X POST "https://YOUR-LIGHTNING-URL/transcribe/file" \
  -H "Authorization: Bearer replace-me" \
  -F "file=@sample.webm" \
  -F "target_lang=jam" \
  -F "device=auto"
```

## Connect your localhost Django app to it

In your local `.env`:

```env
SCRIBE_USE_REAL_AI=True
SCRIBE_TRANSCRIPTION_BACKEND=lightning_mms
SCRIBE_LIGHTNING_TRANSCRIBE_URL=https://YOUR-LIGHTNING-URL/transcribe/file
SCRIBE_LIGHTNING_TRANSCRIBE_TOKEN=replace-me
SCRIBE_LIGHTNING_TRANSCRIBE_TARGET_LANG=jam
SCRIBE_LIGHTNING_TRANSCRIBE_DEVICE=auto
SCRIBE_LIGHTNING_TRANSCRIBE_MODEL_ID=facebook/mms-1b-l1107
SCRIBE_LIGHTNING_TRANSCRIBE_TIMEOUT=600
SCRIBE_LIGHTNING_TRANSCRIBE_CHUNK_SECONDS=25
```

Then restart Django.

## Test from localhost through your app

Option 1: use the normal record/transcribe flow in WellNest after restarting.

Option 2: benchmark the same audio file against both backends:

```powershell
venv\Scripts\python.exe manage.py benchmark_transcription path\to\audio.webm --backend both --repeat 3
```

If you only want the Lightning path:

```powershell
venv\Scripts\python.exe manage.py benchmark_transcription path\to\audio.webm --backend lightning_mms --repeat 3
```

## Notes

- This is benchmarking the **MMS model on a GPU**, not the same model as
  `gpt-4o-transcribe`.
- Speed may improve a lot while transcript quality may differ.
- First run can still be slow because Lightning has to download the MMS model
  into cache.
