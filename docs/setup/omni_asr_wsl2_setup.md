# OmniASR WSL2 Setup — WellNest Triage Lab

Complete record of how omniASR (Meta omnilingual-asr, fairseq2-based) was set up on a Windows machine for local Patois ASR benchmarking.

---

## Why WSL2?

`omnilingual-asr` depends on `fairseq2`, which has a native C++ binary (`fairseq2n`). Meta only publishes Linux wheels — there are no Windows distributions. Running under WSL2 (Ubuntu) gives a full Linux environment while keeping the project on the Windows filesystem.

---

## Machine specs (at time of setup)

- Windows 10 Pro
- NVIDIA RTX 3060 (12 GB VRAM)
- NVIDIA driver 595.97, CUDA 13.2
- WSL2 kernel

---

## 1. Install WSL2 Ubuntu

### Check existing distros
```powershell
wsl --list --verbose
```

### Install Ubuntu (if not present)
Run in **PowerShell as admin**, then restart when prompted:
```powershell
wsl --install -d Ubuntu
```

### Move to a different drive (optional — we used F:)
```powershell
# Stop it first
wsl --terminate Ubuntu

# Export to target drive
wsl --export Ubuntu "F:\WSL\ubuntu.tar"

# Remove from C:
wsl --unregister Ubuntu

# Reimport to F:
wsl --import Ubuntu "F:\WSL\Ubuntu" "F:\WSL\ubuntu.tar" --version 2

# Clean up the tar
Remove-Item "F:\WSL\ubuntu.tar"
```

### Open Ubuntu WSL terminal
```powershell
wsl -d Ubuntu
```
When imported via `--import`, the distro runs as root with no first-time setup prompt.

---

## 2. Install system dependencies inside Ubuntu

```bash
apt-get update -qq

# Python 3.12 (Ubuntu 26.04 ships 3.14 — fairseq2n has no 3.14 wheels)
apt-get install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -qq
apt-get install -y python3.12 python3.12-venv python3.12-dev

# MySQL client headers (for mysqlclient Python package)
apt-get install -y pkg-config default-libmysqlclient-dev

# Audio processing
apt-get install -y libsndfile1 ffmpeg
```

### Why Python 3.12?
Ubuntu 26.04 defaults to Python 3.14. `fairseq2n` only publishes wheels for Python up to 3.12. The `pip install omnilingual-asr` will fail silently with "no matching distribution" on 3.14.

---

## 3. Install CUDA runtime in WSL

The NVIDIA GPU is already accessible in WSL2 via the Windows driver bridge (confirmed with `nvidia-smi` inside WSL). But the CUDA runtime libraries (`libcudart.so`) need to be installed separately inside the Linux environment.

```bash
# Add NVIDIA CUDA repo for WSL-Ubuntu
wget -q https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
apt-get update -qq

# Install CUDA 13.2 runtime (matches driver CUDA version)
apt-get install -y cuda-cudart-13-2
```

Verify GPU is visible:
```bash
nvidia-smi
```
Expected output shows RTX 3060, Driver 595.97, CUDA 13.2.

---

## 4. Create the Python 3.12 venv

```bash
cd /mnt/c/xampp/htdocs/WellnestScribe

# Create venv with Python 3.12 specifically
python3.12 -m venv .venv-wsl

source .venv-wsl/bin/activate
```

`.venv-wsl/` is already in `.gitignore`.

> **Important:** Always use `python3.12 -m venv`, not `python3 -m venv`. The latter uses 3.14 on Ubuntu 26.04.

---

## 5. Install project dependencies

```bash
pip install -r requirements.txt
```

If this fails with `pkg-config: not found` or MySQL errors, run step 2 first.

---

## 6. Install torch with CUDA support

The `omnilingual-asr` pip install pulled in `torch 2.8.0` (CUDA) but `torchaudio 2.11.0+cpu` (CPU-only) — a mismatched pair. Force-reinstall a matched CUDA set:

```bash
pip install torch==2.6.0 torchaudio==2.6.0 \
    --index-url https://download.pytorch.org/whl/cu126 \
    --force-reinstall
```

**Why CUDA 12.6 with a 13.2 driver?** NVIDIA drivers are backwards compatible — a CUDA 13.2 driver runs CUDA 12.x code fine. torch 2.6.0 + cu126 is a stable, known-good build. The default PyPI torch wheel is CUDA-linked but `torchaudio` from PyPI may be CPU-only, causing the version split.

---

## 7. Install omniASR stack

```bash
pip install omnilingual-asr jiwer silero-vad
```

Versions installed:
- `omnilingual-asr 0.1.0`
- `fairseq2 0.6` + `fairseq2n 0.6`
- `jiwer 4.0.0`
- `silero-vad 6.2.1`

---

## 8. Download the omniASR model weights (~2 GB, one-time)

```bash
python manage.py download_triage_models --omni --skip-mms --skip-t5
```

Weights land in `~/.cache/fairseq2/` (or `OMNI_CACHE_DIR` from `.env` if set).

To verify afterwards:
```bash
python3 -c "from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline; print('OK')"
```

---

## 9. Run the dev server from WSL

Every session:
```bash
cd /mnt/c/xampp/htdocs/WellnestScribe
source .venv-wsl/bin/activate
python manage.py runserver
```

Open `http://localhost:8000` in your Windows browser as normal. The Django server running in WSL is accessible on the same localhost.

> Database (MySQL via XAMPP) runs on Windows — accessible from WSL at `localhost` or `$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}')` if localhost doesn't resolve. The `.env` `DATABASE_URL` should already point to the right host.

---

## 10. Using omniASR in the Triage Lab

1. Open `/scribe/triage/`
2. Load or record audio
3. Backend → **omniASR CTC 1B v2**
4. Lang code → `jam_Latn` (Jamaican Creole)
5. Device → **CUDA**
6. Optionally paste a reference transcript for WER/CER scoring
7. Click **Run backend**

The result panel shows:
- Transcript
- Timing breakdown: load ms · preprocessing ms · inference ms
- Chunk count + audio duration
- RTF (realtime factor — lower is faster)
- CER / WER if reference was provided (CER is the headline metric for Patois)

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `No matching distribution found for fairseq2n` | Python version >3.12 | Use `python3.12 -m venv` |
| `libcudart.so.13: cannot open shared object file` | CUDA runtime not in WSL | `apt install cuda-cudart-13-2` |
| `No module named 'torch.sparse'` | torchaudio CPU build + CUDA torch mismatch | Reinstall with `--index-url .../whl/cu126` |
| `omnilingual-asr is not installed` during download | Import failure due to above | Fix torch first, then re-run download |
| `/mnt/c/...` not found | C: drive not mounted | `mkdir -p /mnt/c && mount -t drvfs C: /mnt/c` |
| MySQL connection refused | XAMPP MySQL not running | Start XAMPP MySQL on Windows |
