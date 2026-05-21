# WellNest Scribe — Pilot Cost & Latency Analysis

**Prepared:** May 2026  
**Scope:** Jamaican primary care pilot — 100 and 200 patient encounters/day  
**Author context:** Built on Django 5, MMS-1B Patois ASR, GPT-5 SOAP notes, GPT-4o Transcribe for English doctor mode

---

## 1. Architecture Overview (what runs per encounter)

```
NURSE TRIAGE MODE (Patois patient)
──────────────────────────────────
Patient speaks Patois
  → MMS-1B-l1107 (Jamaican ASR) — GPU cloud     ← compute cost
  → Gemma 4 E2B (Patois → clinical English)     ← GPU cost (same instance)
  → GPT-5 on Azure (SOAP note generation)       ← API cost

DOCTOR MODE (English)
─────────────────────
Doctor dictates / records consultation
  → GPT-4o Transcribe (speech → text)           ← API cost
  → GPT-5 on Azure (finalise / update SOAP)     ← API cost
```

---

## 2. Pricing Assumptions

| Service | Rate | Source |
|---|---|---|
| GPT-5 (Azure) — input tokens | $1.00 / 1M tokens | User-stated |
| GPT-5 (Azure) — output tokens | $4.00 / 1M tokens | Standard 4× output markup |
| GPT-4o Transcribe | $0.006 / min audio | OpenAI API current rate |
| MMS GPU compute (Lightning AI L4) | $0.50 / hr (serverless, pay per use) | Lightning AI estimate |
| Azure App Service hosting | $14.00 / month | User-stated |
| PostgreSQL database | $30.00 / month | User-stated |

> **GPT-5 output rate is an estimate** — Azure has not published the final output price at time of writing.  
> If it differs, adjust the SOAP cost column below proportionally.

---

## 3. Per-Encounter Cost Breakdown

### 3a. Nurse Triage Encounter (10-min Patois audio)

| Step | Input | Compute time | Cost |
|---|---|---|---|
| MMS transcription (GPU) | 10 min audio | ~1.5 min L4 GPU | **$0.013** |
| Gemma 4 E2B interpretation | ~1,200 tokens transcript | ~20 sec (same GPU) | **$0.002** |
| GPT-5 SOAP note | ~2,500 in / ~800 out tokens | API call | **$0.006** |
| **Subtotal** | | | **~$0.021** |

### 3b. Doctor Consultation Encounter (15-min English audio)

| Step | Input | Compute time | Cost |
|---|---|---|---|
| GPT-4o Transcribe | 15 min audio | API (~30 sec) | **$0.090** |
| GPT-5 SOAP update | ~2,000 in / ~700 out tokens | API call | **$0.005** |
| **Subtotal** | | | **~$0.095** |

### 3c. Combined Per Patient (nurse triage + doctor consult)

```
$0.021  (nurse Patois triage)
$0.095  (doctor English mode)
──────
$0.116  per patient  (~12 cents)
```

---

## 4. Monthly Cost Projections

Assuming **22 working days/month**.

### 100 patients/day → 2,200 encounters/month

| Item | Monthly Cost |
|---|---|
| Azure App Service | $14.00 |
| PostgreSQL | $30.00 |
| MMS GPU compute (2,200 × $0.013) | $28.60 |
| Gemma 4 E2B GPU compute | $4.40 |
| GPT-4o Transcribe (2,200 × $0.09) | $198.00 |
| GPT-5 SOAP notes (2,200 × $0.011) | $24.20 |
| **Total** | **~$299 / month** |

> GPT-4o Transcribe dominates. Switching to **GPT-4o-mini-transcribe ($0.003/min)** halves that line:  
> → $99.00 instead of $198.00 → **Total ~$200/month**

### 200 patients/day → 4,400 encounters/month

| Item | Monthly Cost |
|---|---|
| Azure App Service | $14.00 |
| PostgreSQL | $30.00 |
| MMS GPU compute (4,400 × $0.013) | $57.20 |
| Gemma 4 E2B GPU compute | $8.80 |
| GPT-4o Transcribe (4,400 × $0.09) | $396.00 |
| GPT-5 SOAP notes (4,400 × $0.011) | $48.40 |
| **Total** | **~$554 / month** |

> With mini-transcribe: **~$356/month**

### Summary table

| Volume | GPT-4o Full | GPT-4o Mini |
|---|---|---|
| 100 patients/day | ~$299/mo | ~$200/mo |
| 200 patients/day | ~$554/mo | ~$356/mo |
| Per patient cost | ~$0.136 | ~$0.091 |

---

## 5. GPU Hosting — Dedicated vs Serverless

### Option A: Serverless GPU (pay per inference — recommended for pilot)

Best for ≤150 patients/day. You only pay when a job runs.

| Provider | GPU | Rate | MMS job cost (10-min audio) |
|---|---|---|---|
| Lightning AI | L4 24 GB | ~$0.50/hr | ~$0.013 |
| RunPod Serverless | A10G 24 GB | ~$0.44/hr | ~$0.011 |
| Modal.com | A10G | ~$0.19/GPU-min | ~$0.009 |

### Option B: Dedicated GPU VM (always-on — better for ≥150 patients/day)

| GPU | Hourly | Monthly | Break-even encounters |
|---|---|---|---|
| T4 16 GB (GCP) | $0.35/hr | ~$252 | ~2,200 |
| A10G 24 GB (Lambda Labs) | $0.60/hr | ~$432 | ~3,800 |
| L4 24 GB (GCP) | $0.55/hr | ~$396 | ~3,500 |

> At 100 patients/day (2,200 encounters/month), **serverless is cheaper**.  
> At 200 patients/day (4,400 encounters/month), a **dedicated T4 or L4 saves ~$100-150/month**.

---

## 6. Latency Estimates

### 6a. Upload mode (10-min audio file dropped after encounter)

| Step | CPU only | GPU (L4/A10G) |
|---|---|---|
| File upload (5 MB webm) | 3–8 sec | 3–8 sec |
| MMS transcription | **12–18 min** ❌ | **60–120 sec** ✓ |
| Gemma interpretation | **4–8 min** ❌ | **15–25 sec** ✓ |
| GPT-5 SOAP note | 10–20 sec | 10–20 sec |
| **Total end-to-end** | **~20–26 min** ❌ | **~1.5–2.5 min** ✓ |

**CPU is not viable for production.** GPU is required for under-3-minute turnaround.

### 6b. Conversation mode (live streaming, real-time)

Audio is processed in ~30-second chunks as the nurse records.

| Step | GPU latency per chunk |
|---|---|
| MMS transcription (30-sec chunk) | 3–6 sec |
| Gemma interpretation (per chunk) | 5–10 sec |
| Demographic field extraction | 8–12 sec (after full recording) |
| GPT-5 SOAP note | 10–20 sec (after full recording) |
| **Perceived wait after recording stops** | **~15–30 sec** ✓ |

Conversation mode on GPU feels near-instant — the user sees the note building in real time.

### 6c. Doctor English mode (GPT-4o Transcribe)

| Audio length | API latency |
|---|---|
| 5 min | 10–20 sec |
| 10 min | 20–40 sec |
| 20 min | 40–80 sec |

GPT-4o Transcribe is a cloud API — latency is very consistent and unaffected by local hardware.

---

## 7. Cost-Reduction Options

| Change | Saving | Trade-off |
|---|---|---|
| Use GPT-4o-mini-transcribe instead of GPT-4o | ~33% of total cost | Slightly lower accuracy on accented speech |
| Run MMS on dedicated GPU at 200+ patients/day | ~$100-150/mo vs serverless | Upfront commitment |
| Use Gemma 4 E2B locally on GPU (already implemented) | Interpreter is free | Requires GPU host |
| Cache repeated drug/condition prompts | Minor | Low effort |
| Batch SOAP generation (end of session) | Negligible | Already the architecture |

---

## 8. Institutional Pricing Suggestion

Based on cost + margin:

| Tier | Patients/day | Cost/mo | Suggested price/mo | Margin |
|---|---|---|---|---|
| Small clinic | 50 | ~$150 | $350 | 57% |
| Medium clinic | 100 | ~$299 | $600 | 50% |
| Health centre | 200 | ~$554 | $999 | 45% |
| Hospital dept | 400 | ~$1,050 | $1,800 | 42% |

> These prices include a 24/7 support margin. Adjust for local market — JMD equivalent: 1 USD ≈ 157 JMD at time of writing.

---

## 9. Questions for Your Pricing Model

If you share this with another AI for deeper modelling, the key variables to tune are:

1. **Is GPT-4o Transcribe used for every doctor encounter, or only when English mode is explicitly selected?** (Doctor may sometimes speak Patois too)
2. **What is the split between nurse-triage-only vs full-pipeline encounters?** Some patients may not need a SOAP note (quick follow-up, repeat prescription).
3. **Will the GPU host run 24/7 or scale to zero overnight?** Affects dedicated vs serverless decision.
4. **What is the average SOAP note token count?** Longer specialties (psych, geriatrics) will have higher GPT-5 costs.
5. **Is the doctor also recording, or only the nurse?** If both record, double the GPT-4o Transcribe line.

---

*Generated by WellNest Scribe internal tooling. All pricing is an estimate — verify current rates at azure.com, openai.com, and your chosen GPU cloud before committing.*
