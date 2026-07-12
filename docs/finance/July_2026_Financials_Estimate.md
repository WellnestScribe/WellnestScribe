# WellNest — July 2026 Financials Estimate

**Internal working doc · built from the app's own measured data + live vendor prices.**
Every number below is derived with the arithmetic shown, so you can audit each step.

Confidence tags: **[Measured]** = from our own logged data · **[Vendor]** = published price we
pasted/verified · **[Assumption]** = a stated planning input you can change · **[Derived]** = arithmetic
on the above.

---

## 0. Bottom line (read this first)
- **One note costs us ~$0.05** on the recommended single-call pipeline (~$0.11 on the current
  two-call pipeline). **omniASR transcription is a rounding error (~3¢/audio-hour, measured); GPT-5.4
  is ~90% of the cost.**
- **At US$94/month, a doctor is 68–74% margin up to ~15 patients/day, ~58% at 25/day, and still
  profitable (~42%) at 40/day.** No doctor loses us money at $94 on single-call.
- **The single highest-value action is flipping the pipeline from two-call to one-call**
  (`SCRIBE_COMBINED_PIPELINE=True` + a Patois quality check). It roughly halves our only real cost and
  lifts every margin 8–15 points. It is **not** "Mini" — same GPT-5.4 model, one call instead of two.
- **Heavy/hospital doctors (25–40+/day, 36-hour shifts) go to Professional (US$190)** → 64–71% margin.

---

## 1. Measured inputs (the ground truth)

### 1.1 omniASR transcription cost — **[Measured]**
Pulled 2026-07-10 from **93 real `ScribeSession.timings` rows** in the app database.
- GPU: **Nvidia T4 on Modal**. **[Vendor]** rate = **$0.000164 / GPU-second** (Modal pricing page).
- Measured ratio: **0.055 GPU-seconds per 1 second of audio** (median across 71 realistic-length
  sessions; the GPU runs ~18× faster than real time). Consistent for short notes, 5-min+ notes, and
  even the 86-minute upload.

**[Derived] omniASR cost per audio-hour on T4:**
```
0.055 GPU-sec/audio-sec  ×  $0.000164 /GPU-sec  ×  3600 audio-sec/hour
  = $0.0325 per audio-hour
```
→ **A full hour of speech costs ~3.25¢ to transcribe.** A 20-minute recording = ~1.1¢.
*(Buffer for Modal billing the whole request + occasional 27-second cold starts: budget an effective
**~$0.05/audio-hour**. Keeping one warm instance during clinic hours avoids most cold starts.)*

### 1.2 GPT-5.4 note-generation price — **[Vendor]**
- **$2.50 / 1,000,000 input tokens**
- **$15.00 / 1,000,000 output tokens** (reasoning tokens bill at this output rate)
- GPT-5.5 exists at double the price; **we pin 5.4** — right call for a production scribe at this scale.

### 1.3 Pipeline shape — **[Measured, confirmed in code]**
- The app currently runs **two GPT-5.4 calls per note** (Patois-interpret **then** SOAP-generate).
  Confirmed two ways: 81/94 logged sessions show `pipeline_mode:"two-call"`, and in code
  `SCRIBE_COMBINED_PIPELINE` defaults to `False` and is unset in `.env`, so the single-call path is off.
- The **single-call path already exists and auto-falls-back to two-call on error**
  (`run_interpret_and_generate_soap`). Enabling = one env flag + a quality test.

### 1.4 Fixed platform cost — **[Assumption, from infra bills]**
Hosting (Render) + database (Aiven MySQL) + Azure cognitive services ≈ **$75–150/month total**, spread
across active doctors. Use **~$15/doctor/month** early; it **falls as you add doctors** (fixed cost
amortises), so margins *improve* with scale.

---

## 2. Session length — what "a note" actually is

### 2.1 Consult length — **[Assumption, sourced]**
Published primary-care visit lengths: **~10–20 minutes** (US mean ~18, UK ~10). But the scribe only
bills for **spoken audio**, and a visit contains exam, silence, typing and thinking that isn't
continuous speech.

### 2.2 What our own data shows — **[Measured]**
Logged audio per note averages **~3 minutes** (median 1.4). Those are largely test/dictation sessions,
but they confirm real usage skews **short**, not 20 minutes.

### 2.3 The planning range we use
| Mode | Audio/note | When |
|---|---|---|
| Dictation / summary | ~5 min | doctor speaks a summary after the visit |
| **Typical (planning number)** | **~12 min** | ambient capture of the key discussion |
| Full ambient (worst case) | ~20 min | records the entire consult end-to-end |

**The 20-minute figure is the worst case, not the norm.** We plan on **12 min** and note that real
data (~3 min) only makes margins *better*.

---

## 3. Cost per note — full token-level math

**Token assumptions — [Assumption, standard heuristics]:** speaking rate ~150 words/min; tokens ≈
words × 1.3 → **~195 tokens per audio-minute** of transcript. System/format/Patois prompt ≈ 1,000
tokens. SOAP note output ≈ 700 tokens. Medium reasoning ≈ 1,200 tokens (billed at $15/1M).

### 3.1 Single-call (recommended)
One GPT-5.4 call: input = transcript + prompt; output = the SOAP note; plus reasoning.

**5-minute note** (transcript ≈ 5 × 195 = 975 tokens):
```
input   (975 + 1000)=1,975 tok × $2.50/1M = $0.00494
output  700 tok            × $15/1M       = $0.01050
reason  1,200 tok          × $15/1M       = $0.01800
GPT-5.4 subtotal                          = $0.0334
omniASR 5 audio-min        (§1.1)         = $0.0027
                                    NOTE  ≈ $0.036
```
**20-minute note** (transcript ≈ 3,900 tokens):
```
input   (3,900 + 1000)=4,900 × $2.50/1M = $0.01225
output  700           × $15/1M          = $0.01050
reason  1,200         × $15/1M          = $0.01800
GPT-5.4 subtotal                        = $0.0408
omniASR 20 audio-min                    = $0.0108
                                  NOTE  ≈ $0.052
```
→ **Single-call note ≈ $0.04 (short) to $0.05 (long).** Barely scales with length, because omniASR is
tiny and the note output + reasoning are ~fixed.

### 3.2 Two-call (current) — why it's ~2× worse
Adds a first "interpret" call that **re-outputs the whole transcript** (at the $15/1M output rate — the
expensive part), before the generate call.

**20-minute note:**
```
Call 1 (interpret):
  input   (3,900 + 1,200)=5,100 × $2.50/1M = $0.01275
  output  3,900 (cleaned transcript) × $15/1M = $0.05850   ← the killer
  reason  800 × $15/1M                     = $0.01200
  subtotal                                 = $0.0833
Call 2 (generate): (same as single-call above) = $0.0408
GPT-5.4 total                                  = $0.124
omniASR                                        = $0.0108
                                        NOTE   ≈ $0.135
```
**5-minute two-call ≈ $0.068.**

### 3.3 Cost-per-note summary
| | 5-min note | 12-min note | 20-min note |
|---|---|---|---|
| **Single-call (recommended)** | ~$0.036 | ~$0.045 | ~$0.052 |
| Two-call (current) | ~$0.068 | ~$0.09 | ~$0.135 |
| **Saving from merging** | ~1.9× | ~2.0× | ~2.6× |

---

## 4. Cost per doctor per month, by volume

**Planning basis: single-call, 12-min average note = ~$0.045/note, + $15/mo infra.**
`notes/month = patients/day × working days` (22 working days, except the 36-hour-shift row).

| Profile | Patients/day | Notes/mo | AI cost (×$0.045) | + infra | **Total cost/mo** |
|---|---|---|---|---|---|
| Light clinic | 10 | 220 | $9.90 | $15 | **$24.90** |
| Typical GP | 15 | 330 | $14.85 | $15 | **$29.85** |
| Busy private | 25 | 550 | $24.75 | $15 | **$39.75** |
| Heavy / hospital | 40 | 880 | $39.60 | $15 | **$54.60** |
| **36-hour ED shifts** | ~55 eq. | ~1,200 | $54.00 | $15 | **$69.00** |

*The 36-hour-shift row: a hospital/ED doctor on long continuous shifts sees more patients per shift but
fewer shift-days; what matters is the **monthly note total**. ~1,200 notes/month models a very heavy ED
run (e.g. ~8 × 36-hour shifts, ~40 patients each, plus clinic).*

---

## 5. Margins per tier (with the math)

`margin = (price − cost) / price`. Costs from §4 (single-call).

### 5.1 Standard — **US$94/month** (J$15,000)
| Profile | Cost/mo | **Margin @ $94** |
|---|---|---|
| Light (10/day) | $24.90 | **74%** |
| Typical (15/day) | $29.85 | **68%** |
| Busy (25/day) | $39.75 | **58%** |
| Heavy (40/day) | $54.60 | **42%** |
| ED 36-hr (1,200/mo) | $69.00 | **27%** |

**Standard holds ≥65% up to ~15–18 patients/day, and never goes unprofitable — even a 40/day doctor is
+42%.** (On the *current* two-call pipeline, a 40/day doctor is ~$94 cost = break-even — which is
exactly why we merge.)

### 5.2 Professional — **US$190/month** (J$30,000)
Same costs, higher price — where busy/hospital doctors belong.
| Profile | Cost/mo | **Margin @ $190** |
|---|---|---|
| Busy (25/day) | $39.75 | **79%** |
| Heavy (40/day) | $54.60 | **71%** |
| ED 36-hr (1,200/mo) | $69.00 | **64%** |

### 5.3 EMR add-on — **+US$50/month**
The EMR's marginal cost is **near zero** (database + storage, cents). At +$50 the add-on is **~95–100%
margin** — and it's the retention moat (once a clinic's records live in WellNest, they don't leave).
Price it to *spread*, not to milk.

### 5.4 Institution — **from US$76/seat/month** (min 10 seats)
Public-sector per-seat usage is typically moderate (~60 audio-hours/seat). At light usage cost ≈
$20–25/seat → **margin ~68–74%**. Cap per-seat audio to protect it against a heavy outlier.

### 5.5 Clinic Resilience (offline node) — **one-time hardware, separate**
CanaKit Pi 4 Extreme Kit **[Vendor] ~US$190**; landed in Jamaica **~$250–300** (import ~17–40% + courier).
Charge as a **one-time ~US$290 hardware + setup**, plus optional **~$15/month** Resilience add-on
(OTA updates, remote monitoring/wipe). **Never fold hardware into the subscription margin** — it's
pass-through and belongs on its own line on the card.

---

## 6. Recommended tier card
| Tier | Price/mo | For | Margin (ceiling → typical) |
|---|---|---|---|
| **Standard** | US$94 | everyday clinic practice, unlimited notes | 42% → 74% |
| **Professional** | US$190 | high-volume & procedural, long recordings ≤5h | 64% → 79% |
| **+ EMR** | +US$50 | add the lightweight EMR to any plan | ~95%+ |
| **Institution** | from US$76/seat (min 10) | hospitals/authorities, invoice/PO | ~68–74% |
| **Clinic Resilience** | one-time ~US$290 + $15/mo | offline blackout continuity (hardware) | pass-through |

Marketing = **"unlimited notes."** The real limit is a generous backend audio allowance the doctor
never sees unless they cross ~80% (§7).

---

## 7. Overuse & runaway handling (never block a note in progress)
The #1 rule: **cutting a doctor off mid-consult could destroy a clinical/legal record — never do it.**
Guardrails, in order:
1. **Per-session auto-stop.** A single recording auto-ends at **3 h (Standard) / 5 h (Professional)**;
   on-screen warning at **90 minutes**. Fixes "someone forgot to stop the recording."
2. **Silence auto-stop.** After ~**10 minutes of continuous silence**, auto-end and save.
3. **Continuation counts to the same meter.** Resuming a paused note **appends to the same session's
   cumulative audio** — you cannot dodge the per-session cap by ending and resuming. Never deletes;
   auto-saves.
4. **Monthly allowance:** no visible meter until **~80%**, then a *complimentary* nudge ("you're one of
   our busiest clinicians — Professional may fit you"), **soft-cap at 100%** (keep working + one-tap
   prorated upgrade). Never a mid-consult popup.
5. **Non-payment:** suspend the **AI**, never the **records** — export always available (DPA-2020 +
   ethics). Records are never held hostage.

---

## 8. Sensitivity — what moves the margin most
| Lever | Effect |
|---|---|
| **Two-call → one-call** | ~2× on GPT = the whole cost line; **+8–15 margin points**. Do this first. |
| Audio length per note | omniASR is tiny, so length mostly affects GPT input tokens — modest. |
| Prompt caching | cached system-prompt input drops to ~$0.25/1M (10× cheaper on the repeated part). |
| Reasoning effort | keep **medium**, not high — reasoning bills at the $15 output rate. |
| Doctor count (scale) | spreads the $75–150 platform cost → per-doctor infra falls, margins rise. |

---

## 9. Measured vs. estimated — and what closes the gap
- **Measured (hard):** omniASR GPU cost, GPU ratio, real audio-per-note, pipeline shape.
- **Estimated (±30%):** GPT-5.4 token counts (we log latency, not tokens yet).
- **Next step to make GPT measured, not estimated:** log **input + output + reasoning tokens per call**
  on each note (task **T5**). Then every number here becomes fact, and prices lock on data.

## 10. Sources
- **Modal pricing** (T4 $0.000164/GPU-sec) — Modal pricing page, pasted 2026-07-10.
- **GPT-5.4 pricing** ($2.50/$15 per 1M) — OpenAI/Azure list price, confirmed 2026-07-10.
- **omniASR cost & GPU ratio** — measured from 93 `ScribeSession.timings` rows, this app, 2026-07-10.
- **Consult length** — published primary-care visit-duration studies (US ~18 min, UK ~10 min).
- **Token heuristics** — ~150 words/min speech; ~1.3 tokens/word (standard tokenizer ratio).
- **Raspberry Pi** — CanaKit Pi 4 Extreme Kit list price + Jamaica Customs duty schedule.

*Companion: cost decisions & tier rationale also summarised in `BUILD_PLAN_2026-07.md` (Decision 2).*
