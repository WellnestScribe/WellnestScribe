# Triage Lab — install commands

All commands run inside the project venv. Activate first:

```powershell
cd c:\xampp\htdocs\WellnestScribe
.\.venv\Scripts\Activate.ps1
```

Verify you're in the venv (prompt shows `(.venv)`). After every install,
restart `python manage.py runserver` and hard-refresh `/scribe/triage/` so
the env probe reflects the new state.

---

## 1. PyTorch — pick ONE

Triage runs everything on PyTorch. Don't install both CPU and CUDA — pick the
build that matches your hardware. If you change your mind, reinstall with
`--upgrade --force-reinstall` so pip replaces the old wheel.

### CPU only (no GPU, or just testing)
```powershell
pip install torch torchaudio
```

### NVIDIA GPU — CUDA 12.1 (most stable for RTX 20/30/40 series)
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### NVIDIA GPU — CUDA 12.4 (newer drivers)
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

### NVIDIA GPU — CUDA 12.6 (latest)
```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
```

> **Why your `cu12` command failed:** the URL takes a 3-digit suffix
> (`cu121`, `cu124`, `cu126`) — not the major version alone. Pip looks
> for an exact directory.

### Force-reinstall (when "CUDA: no" persists)
You probably have the CPU wheel cached. Force pip to replace it:

```powershell
pip install --upgrade --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### Pick the right CUDA build for your driver
Check your NVIDIA driver version:

```powershell
nvidia-smi
```

Map driver → max CUDA you can use:

| NVIDIA Driver | Max CUDA |
|---|---|
| 525.60+ (Windows 528+) | 12.1 |
| 550.54+ | 12.4 |
| 560.28+ | 12.6 |

If `nvidia-smi` says e.g. "CUDA Version: 12.6" you're fine on any build
up to and including 12.6.

### Verify CUDA after install
```powershell
python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no GPU')"
```

---

## 2. Core ML / audio stack (always needed)

These are required for MMS, Omni-ASR, T5, Gemma, and audio I/O:

```powershell
pip install transformers accelerate librosa soundfile sentencepiece
```

| Package | Why |
|---|---|
| `transformers` | HuggingFace model wrapper |
| `accelerate` | Device placement + fp16/bf16 helpers |
| `librosa` | Audio load + resample to 16 kHz |
| `soundfile` | WAV read/write |
| `sentencepiece` | T5 / Gemma tokeniser dependency |

---

## 3. Denoise (optional — Triage "Denoise audio first" toggle)

Triage tries DeepFilterNet first (best quality), falls back to noisereduce.
On Windows DeepFilterNet wheels sometimes fail to build — noisereduce
always works.

### Noisereduce (always works, decent quality)
```powershell
pip install noisereduce
```

### DeepFilterNet (best quality, may fail on Windows)
```powershell
pip install deepfilternet
```

If DeepFilterNet's wheel build fails on Windows, stick with noisereduce —
Triage falls back automatically.

---

## 4. Speaker diarization (optional — Triage "Speaker diarization" toggle)

Triage tries the `diarize` lib first (~8× real-time on CPU), falls back to
`pyannote.audio` 3.1.

### diarize (CPU-friendly)
```powershell
pip install diarize
```

### pyannote.audio (established, needs HF token)
```powershell
pip install pyannote.audio
```

pyannote uses a gated HuggingFace model. Get a free token at
https://huggingface.co/settings/tokens, then either:

- Log in once: `huggingface-cli login` and paste the token, or
- Add to `.env`: `HF_TOKEN=hf_xxxxxxxxxxxxxxxxxx`

You also have to visit
https://huggingface.co/pyannote/speaker-diarization-3.1 and click
"Agree and access repository" once with the same account.

---

## 5. MMS + T5 model weights (the big downloads)

Models live in the HuggingFace cache (`~/.cache/huggingface/hub/`) by default,
or in `models/<slug>/` locally if you drop the safetensors yourself.

### Auto-download via Triage UI
1. Open `/scribe/triage/` as admin
2. Click **"Download MMS + T5 models"** in the env panel
3. Wait — the page polls every 8 s and turns "MMS cached" / "T5 cached" green

### Auto-download via terminal
```powershell
python manage.py download_triage_models
```

### Manual download to project-local folder
Drop the safetensors + tokeniser files in:

```
c:\xampp\htdocs\WellnestScribe\models\google--gemma-4-E2B\
    ├── config.json
    ├── tokenizer.json
    ├── tokenizer_config.json
    └── model.safetensors          (or sharded model-*.safetensors + index.json)
```

The Gemma loader checks `<BASE_DIR>/models/google--gemma-4-E2B/` and
`<BASE_DIR>/models/gemma-4-E2B/` before falling back to HF hub. Env probe
panel shows "Gemma cached: yes (local)" with the resolved path when found.

For MMS / T5, use the HuggingFace cache layout instead (the management
command above handles it).

---

## 6. Reliability metrics (optional — section 5 "Reliability scoring")

```powershell
pip install jiwer
```

Without `jiwer` Triage falls back to a naive Levenshtein WER, slower but
correct. With it you get the standard implementation used in ASR papers.

---

## 7. One-shot "install everything" command (CPU)

If you don't have an NVIDIA GPU yet and just want every Triage feature
available:

```powershell
pip install torch torchaudio transformers accelerate librosa soundfile sentencepiece noisereduce pyannote.audio diarize jiwer
```

GPU equivalent (RTX 2060 with CUDA 12.1):

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install transformers accelerate librosa soundfile sentencepiece noisereduce pyannote.audio diarize jiwer
```

(Two commands — the second uses the regular PyPI index, the first uses
the CUDA wheel index.)

---

## 8. Verifying everything in one shot

```powershell
python -c "import torch, transformers, librosa, noisereduce, jiwer; import pyannote.audio; print('all ok · torch', torch.__version__, '· cuda', torch.cuda.is_available())"
```

If any line errors out, install the missing package from the matching
section above.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: No matching distribution found for torch` | URL typo — use `cu121` not `cu12` |
| Env probe shows `CUDA: no` after install | CPU wheel got cached; rerun with `--upgrade --force-reinstall` (section 1) |
| `import torch` works but `torch.cuda.is_available()` is False | Driver too old (run `nvidia-smi`) or CPU wheel installed |
| `pyannote.audio` errors "401 Unauthorized" | Need HF token + accept model terms (section 4) |
| DeepFilterNet build fails on Windows | Skip it — Triage uses noisereduce automatically |
| `pip install diarize` fails | The lib has limited wheels — use pyannote.audio instead |
| MMS still slow after installing CUDA build | Restart `runserver`, then in the Device dropdown pick **CUDA** before clicking Run backend |
| Triage page shows "Some Python libs are missing" | Section 2 above — `transformers accelerate librosa soundfile sentencepiece` |
