#!/usr/bin/env bash
# ============================================================
# WellNest Scribe — Server ML dependency setup
# Run once on the server (Linux/Ubuntu) before starting the app.
#
# Usage:
#   bash server_setup.sh                # CPU-only (VPS)
#   bash server_setup.sh --cuda         # CUDA 12.1 (GPU server)
#   bash server_setup.sh --model-only   # skip pip, just download models
#   bash server_setup.sh --gemma-large  # also download Gemma 3 4B (gated — needs HF login first)
#
# Prerequisites:
#   Python 3.10+, ~8 GB free disk, internet access
#
# For gated models (Gemma 3 4B, Llama):
#   pip install huggingface_hub
#   huggingface-cli login          ← paste your HF token when prompted
#   then run with --gemma-large
# ============================================================

set -euo pipefail

CUDA=0
MODEL_ONLY=0
GEMMA_LARGE=0

for arg in "$@"; do
  case $arg in
    --cuda)         CUDA=1 ;;
    --model-only)   MODEL_ONLY=1 ;;
    --gemma-large)  GEMMA_LARGE=1 ;;
  esac
done

PYTHON=${PYTHON:-python3}

echo "========================================"
echo "  WellNest Scribe — server setup"
echo "  CUDA build : $CUDA"
echo "  Model-only : $MODEL_ONLY"
echo "  Gemma large: $GEMMA_LARGE"
echo "  Python     : $($PYTHON --version)"
echo "========================================"

# ── 1. Virtual environment ────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "[1/5] Creating virtual environment..."
  $PYTHON -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ── 2. Core Django dependencies ───────────────────────────────────────────────
if [ "$MODEL_ONLY" -eq 0 ]; then
  echo "[2/5] Installing core app dependencies..."
  pip install --upgrade pip wheel

  pip install \
    django \
    django-environ \
    python-decouple \
    whitenoise \
    gunicorn \
    psycopg2-binary \
    openai \
    Pillow

  # ── 3. ML / audio stack ─────────────────────────────────────────────────────
  echo "[3/5] Installing ML + audio dependencies..."
  if [ "$CUDA" -eq 1 ]; then
    echo "       → CUDA 12.1 PyTorch"
    pip install torch torchaudio \
      --index-url https://download.pytorch.org/whl/cu121
  else
    echo "       → CPU-only PyTorch"
    pip install torch torchaudio
  fi

  pip install \
    transformers \
    accelerate \
    sentencepiece \
    librosa \
    soundfile \
    noisereduce \
    huggingface_hub

  # ── 4. Django migrations ─────────────────────────────────────────────────────
  echo "[4/5] Migrating database..."
  python manage.py migrate --run-syncdb
  python manage.py collectstatic --noinput || true

  echo "[4/5] Seeding drug alias table..."
  python manage.py seed_drug_aliases || true
fi

# ── 5. Download ML models ──────────────────────────────────────────────────────
echo "[5/5] Downloading ML models (this takes a while — grab a coffee)..."
echo ""

# MMS 1B-l1107 — Jamaican Patois ASR (~4 GB, always required)
echo "  ── facebook/mms-1b-l1107  (Jamaican Patois ASR, ~4 GB) ──"
python - <<'PYEOF'
from transformers import AutoProcessor, Wav2Vec2ForCTC
print("    processor...")
AutoProcessor.from_pretrained("facebook/mms-1b-l1107")
print("    model weights...")
Wav2Vec2ForCTC.from_pretrained("facebook/mms-1b-l1107")
print("    MMS done.\n")
PYEOF

# Gemma 4 E2B — primary local LLM interpreter (~5 GB, Apache 2.0, no HF token needed)
echo "  ── google/gemma-4-E2B-it  (local Patois interpreter, ~5 GB, no login needed) ──"
python - <<'PYEOF'
from transformers import AutoProcessor, AutoModelForCausalLM
print("    processor...")
AutoProcessor.from_pretrained("google/gemma-4-E2B-it")
print("    model weights...")
AutoModelForCausalLM.from_pretrained("google/gemma-4-E2B-it", dtype="auto")
print("    Gemma 4 E2B done.\n")
PYEOF

# Gemma 3 4B — alternative, gated (needs HF token + --gemma-large flag)
if [ "$GEMMA_LARGE" -eq 1 ]; then
  echo "  ── google/gemma-3-4b-it  (alternative, ~5 GB, requires HF token) ──"
  python - <<'PYEOF'
from transformers import AutoTokenizer, AutoModelForCausalLM
print("    tokenizer...")
AutoTokenizer.from_pretrained("google/gemma-3-4b-it")
print("    model weights...")
AutoModelForCausalLM.from_pretrained("google/gemma-3-4b-it")
print("    Gemma 3 4B done.\n")
PYEOF
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo ""
echo "  Models downloaded to: ~/.cache/huggingface/hub/"
echo ""
echo "  Start the server:"
echo "    source .venv/bin/activate"
echo "    gunicorn wellnest.wsgi:application --bind 0.0.0.0:8000 --workers 2"
echo ""
echo "  Dev server:"
echo "    python manage.py runserver 0.0.0.0:8000"
echo ""
if [ "$GEMMA_LARGE" -eq 0 ]; then
  echo "  Tip: re-run with --gemma-large to also cache Gemma 3 4B"
  echo "       (run 'huggingface-cli login' first — it's a gated model)"
fi
echo "========================================"
