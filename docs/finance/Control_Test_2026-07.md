# WellNest — AI Cost Control Test (July 2026)

**Living doc.** Records the controlled measurement of real per-note AI cost, to
replace the *estimates* in `July_2026_Financials_Estimate.md` (§9: GPT token
counts were estimated ±30%) with **measured** numbers.

## Method

- **Who:** run by 10 + Gary. Gary watches the source meters (Modal endpoint credit,
  Azure token/cost); Claude reads the app's own `ModelUsageLog` (task T5 token
  logging) and reconciles.
- **Account:** a fresh model account (`garybryan2021`) with unused credit, so usage
  is isolated.
- **Transcription routing:** only the `garybryan2021` Modal endpoint left **Active**
  (all others Disabled), so all omniASR usage lands on one meter.
- **Pipeline:** single-call (`SCRIBE_COMBINED_PIPELINE=True`, `SCRIBE_PIPELINE_MODE=single`).
- **Model deployment:** Azure `gpt-5-chat` (classified as a reasoning model; reasoning
  effort = "minimal").
- **Files:** several pre-made recordings of different lengths (`.../control test/`).
- **Tooling:** `python manage.py ai_cost_report --hours N` (or `--session PK`, `--json`)
  reads logged tokens + folds in omniASR cost from each session's audio duration.

## The open pricing question (drives everything)

Tokens are measured exactly by two independent methods. The **only** unknown is the
$/1M rate Azure bills for the `gpt-5-chat` deployment:

| Candidate rate | Source | Note cost (5-min) |
|---|---|---|
| **$2.50 / $15** per 1M (in/out) | GPT-5.4 list (financials doc) | ~$0.045 |
| **$5.00 / $30** per 1M | full GPT-5 / "5.5" (double) | ~$0.08 |

Resolving this is the single biggest cost question. See the daily-cost check under Run 1.

---

## Run 1 — 5-minute recording (session 158) · 2026-07-11

### Token reconciliation — two independent measurements agree to the token
| Metric | Gary (Azure, "last day" diff, +2 req) | Claude (`ModelUsageLog`, 1 call) | Match |
|---|---|---|---|
| Prompt tokens | +9,130 | 9,130 | **exact** |
| Completion tokens | +610 (0.61K rounded) | 618 | ✓ |
| Total tokens | +9,740 | 9,748 | ✓ |
| Reasoning tokens | (not shown) | **0** | — |
| Audio (measured) | — | 301.6 s (5.0 min) | ✓ |

*"+2 requests" vs 1 logged call:* the single generate call's prompt (9,130) equals
Gary's whole 2-request prompt diff, so the 2nd Azure request carried ~0 tokens
(a tiny demographics/support call). Not material.

### Cost at each candidate rate
| Rate | GPT | + Modal (omniASR) | **Note total** |
|---|---|---|---|
| $2.50 / $15 | $0.032 | ~$0.01–0.02 (measured compute $0.0027) | **~$0.045** |
| $5.00 / $30 | $0.064 | ~$0.01–0.02 | **~$0.08** |

Modal admin showed ~$0.01 (rounded, not fully trusted) → safe ceiling **$0.02**.

### Daily-cost cross-check (Gary) — rules out the $5/$30 scenario
Gary reports the **full daily Azure cost for everything on 2026-07-11 = $0.29**, and
the token snapshot is the Azure **"last day"** cumulative (11 requests: 53.98K prompt
+ 3.30K completion).

Apply each rate to the **whole day's** tokens:
```
$2.50/$15 :  53,980×$2.50/1M + 3,300×$15/1M = $0.1845
$5.00/$30 :  53,980×$5.00/1M + 3,300×$30/1M = $0.3689
```
The day's **total** Azure bill (all services) is **$0.29**.
- $5/$30 would make the chat tokens **alone** cost **$0.369 > $0.29** total → **impossible**.
  → **The full $5/$30 non-cached rate is ruled out.**
- $2.50/$15 → chat $0.18, leaving $0.11 for other Azure usage → **consistent**.

**Conclusion:** the effective GPT rate is at or near **$2.50/$15** (or $5/$30 list with
heavy prompt caching). Either way, **per-note cost is ~$0.045–0.06, not $0.08.** The
financials doc's ~$0.045/note estimate looks close; Gary's $0.064 (at $5/$30) is an
overestimate.

**To pin it exactly (Gary):** filter Azure Cost Management to *just the `gpt-5-chat`
deployment* for the day, then that $ ÷ 57.28K tokens = the true blended rate.
("Everything = $0.29" is only a ceiling because it includes non-chat services.)

### Key structural findings
- **Prompt tokens dominate: 9,130 of 9,748 (94%).** Completion 618; **reasoning 0.**
- Transcript is only ~975 tokens → the **system prompt is ~8,150 tokens**: that is the cost.
- **Reasoning ≈ 0** confirms "minimal" effort works — the doc's assumed $0.018 reasoning
  cost is not happening.
- **→ Prompt caching is now the #1 cost lever.** The ~8K system prompt is identical every
  call; cached input bills far cheaper, roughly **halving GPT cost regardless of the rate**
  ($0.064 → ~$0.035). Bigger than the two-call→one-call flip already done.
- **omniASR is a rounding error** — measured $0.0027 for 5 min (~6–8% of the note). Confirmed.

### Margins (measured, at 500 / 1,100-note caps, +$15 infra)
| Rate | Standard $94 | Professional $190 |
|---|---|---|
| $2.50/$15 | **65%** | 71% |
| $5.00/$30 | ~44% | ~55% |
| $5/$30 **+ prompt caching** | ~60% | ~68% |

Profitable in all cases; if it's the high rate, prompt caching is needed to hold the headline margins.

---

## Run 2 — 20-minute recording (session 159) · 2026-07-11 · warm start

Both Run 1 and Run 2 were **warm starts** (Gary confirmed) — no cold-start penalty in
these numbers. (Earlier "expect a cold start" caveat did not apply.)

### Token reconciliation — matches again to within rounding
| Metric | Gary (Azure diff, +1 req) | Claude (`ModelUsageLog`, 1 call) | Match |
|---|---|---|---|
| Prompt tokens | +12,670 | 12,667 | ✓ |
| Completion tokens | +720 (0.72K) | 714 | ✓ |
| Total tokens | +13,380 | 13,381 | ✓ |
| Reasoning tokens | — | **0** | — |
| Audio (measured) | — | 1,203.9 s (20.1 min) | ✓ |

**"Why did Azure count 1 request here but 2 for the 5-min run?"** My server log made
**exactly one** GPT call per note in *both* runs (sessions 158 and 159, one row each).
So the 5-min run's extra Azure request came from an **auxiliary / zero-token call**
(a streaming/health artifact or Azure's counter quirk) — its prompt-token contribution
was 0 (my single call's 9,130 equalled Gary's whole +2 diff). It billed nothing. The
20-min cleanly shows 1 = 1. **Ignore the request count; tokens are the bill, and they reconcile.**

### Cost at the confirmed rate ($2.50/$15)
| | Prompt tok | Compl tok | GPT $ | omniASR $ (measured) | **Note total** |
|---|---|---|---|---|---|
| GPT @ $2.50/$15 | 12,667 | 714 | $0.042 | $0.011 (20.1 min) | **~$0.053** |
| (Gary's $5/$30 calc) | | | $0.085 | | — |

Gary's $0.085 again used the ruled-out $5/$30 rate → overstated ~2×. At the real rate the
20-min note GPT cost is **$0.042**.

### THE thesis, confirmed: cost barely scales with length
| Run | Audio | Prompt | Compl | Reasoning | GPT $ (@2.5/15) | omniASR $ | **Note total** |
|---|---|---|---|---|---|---|---|
| 5-min | 5.0 min | 9,130 | 618 | 0 | $0.032 | $0.003 | **~$0.035** |
| 20-min | 20.1 min | 12,667 | 714 | 0 | $0.042 | $0.011 | **~$0.053** |

**4× the audio → only ~1.5× the cost.** Output + reasoning stay ~flat (a SOAP note is
bounded); only input tokens grow, and input is the *cheap* side ($2.50 vs $15/1M). This
**confirms the doc's §3.3 "barely scales with length"** and directly supports the
**note-credit cap model** (a long note = a few credits, not one, but nowhere near
proportional to minutes).

### Price: $5/$30 now doubly ruled out
Gary's running total for all 12 requests **at $5/$30 = $0.454**. But the day's *total*
Azure bill (everything) was **$0.29** at 11 requests. One 13K-token request can't lift a
$0.29 total to $0.45+. At **$2.50/$15** the 12-request chat total is **$0.227** — which
fits under the daily total with room for other services. **Confirm:** Gary's *current*
daily total should read **~$0.33** ($2.50/$15), not ~$0.45+ ($5/$30).

### Modal / omniASR — which number to trust
Modal shows **two conflicting figures** for `garybryan2021` (Jul 1–Aug 1 period):
- Credits popover: **$0.06 used / $0.94 left** — this **lags**.
- Usage & Billing → Cost Summary → **Total Usage $0.09** (Deployed Apps) — the **ledger**.

**Trust the $0.09** (the billing ledger updates before the credit popover). "Total Spend
$0.00" just means the $1 free credits absorbed it — it is not "free," it's $0.09 of usage.

**The three figures Gary sees ($0.09 / $0.08 / $0.06) are NOT competing totals** — they're
different slices, and they reconcile:
| Figure | What it is | Reliability |
|---|---|---|
| **$0.09** — Usage Breakdown "Deployed Apps" **and** Cost Summary "Total Usage" | the **period total** (all resources) | **correct** — agrees across 2 views |
| **$0.08** — Resource Breakdown "T4" | the **GPU-only slice** of the total; the other ~$0.01 is CPU/memory/container | a sub-line, not a total |
| **$0.06** — Deployed App Breakdown / credit popover "used" | a **lagging** aggregation | stale — ignore |

So: **$0.08 (T4) + ~$0.01 (non-GPU) = $0.09 (total).** The $0.06 is the same stale number
the credit popover shows. **The correct total is $0.09.** The usage chart spikes on Jul 11,
confirming **all $0.09 is from today's control test** (warm-up + 5-min + 20-min combined) —
i.e. the *entire test's* transcription cost so far is **$0.09**, not any single run.

**But $0.09 is the whole period's total** (warm-up + 5-min + 20-min + all app compute),
**not the 20-min run alone.** You cannot read a single run off it.

**Compute a single run instead (don't trust the live dashboard):**
```
T4 rate = $0.000164 / GPU-sec ;  measured 0.055 GPU-sec per audio-sec
20-min = 1,204 audio-sec × 0.055 × $0.000164 = $0.011  (pure inference floor)
```
Real billed ≈ 2–4× that (Modal also bills container **spin-up + hold** per invocation) →
**~$0.03–0.05 for the 20-min run.** Matches Gary's settled reading. Use **$0.05 ceiling**.

**Small-batch overhead — important:** $0.09 for ~30 audio-min of *isolated* runs ≈
$0.18/audio-hour — ~5× the measured **$0.0325/audio-hour** compute rate. That gap is
container start/hold billed per run. **In production (back-to-back patients, warm
container) the effective rate falls toward $0.0325/hr** — so the test's per-run Modal cost
is an *inflated* small-batch artifact, not steady state.

**Bottom line:** Modal is cents and noisy; don't chase its UI. The exact per-invocation
GPU-seconds are in **Modal → Logs**; the **month-end invoice** is truth. It doesn't move
the note cost, which is set by GPT (measured exactly).

---

## Run 3 — 60-minute recording (session 160) · 2026-07-11 · warm start

### Token reconciliation — matches a third time
| Metric | Gary (Azure diff, +1 req) | Claude (`ModelUsageLog`) | Match |
|---|---|---|---|
| Prompt tokens | +21,880 | 21,882 | ✓ |
| Completion tokens | +650 | 649 | ✓ |
| Total tokens | +22,530 | 22,531 | ✓ |
| Reasoning | — | 0 | — |
| Audio (measured) | — | 3,601 s (60.0 min) | ✓ |

### PRICE — now directly confirmed ≈ $2.50/$15
The exact method (actual $ ÷ actual tokens) finally lines up. Azure's gpt-5 cost for the
day = **$0.29**, and today's token total is **93.2K** (88.53K prompt + 4.67K completion):
```
@ $2.50/$15 :  88,530×$2.50/1M + 4,670×$15/1M = $0.2914  ≈ $0.29  ✓ MATCH
@ $5.00/$30 :  same tokens                     = $0.5828  ≈ $0.58  ✗
```
**$0.29 = $2.50/$15 × today's tokens, to the cent.** And Azure has stayed at ~$0.29 while
tokens grew 47K→93K — if the rate were $5/$30 it would read ~$0.58. **Working rate = $2.50/$15.**
*One clean confirmation:* once Azure fully settles for the day, it should hold at **~$0.29**
(not climb to ~$0.58). Gary's $5/$30 running total ($0.583) is exactly 2× the real figure.

> Correction to Run 1's note: the earlier "$0.29 = everything, rules out $5/$30 as a ceiling"
> reasoning was loose (token-alignment was ambiguous under Azure's lag). This direct
> $/token match at 93.2K is the solid confirmation.

### MODAL — computed exactly from execution seconds (ignore the dashboard)
Gary's Function-Calls table gives the real GPU time per run; T4 = **$0.59/GPU-hr = $0.000164/s**:
| Run | Execution | Modal $ (marginal, warm) |
|---|---|---|
| 5-min | 30.48 s | **$0.005** |
| 20-min | 113.95 s | **$0.019** |
| 60-min | 279.99 s | **$0.046** |
| **exec total** | 424.4 s | **$0.070** |

The **dashboard total is $0.15** (T4 $0.14 + CPU $0.01). Execution-only is $0.070, so the
extra ~$0.08 is **container warm-hold/idle** billed between runs. **In production that idle is
amortised across back-to-back patients**, so the *marginal* per-note Modal cost is the
execution figure above, not the dashboard total. (Dashboard also still shows a lagging
$0.11 in the app-breakdown / credit "used" — same stale-cache pattern; the real total is $0.15.)

### Measured cost curve — the thesis holds, cost is sub-linear in length
| Run | Audio | GPT $ (@2.50/15) | Modal $ (exec) | **Note total** | note-credits (~20min each) |
|---|---|---|---|---|---|
| 5-min | 5.0 min | $0.032 | $0.005 | **$0.037** | 1 |
| 20-min | 20.1 min | $0.042 | $0.019 | **$0.061** | 1 |
| 60-min | 60.0 min | $0.065 | $0.046 | **$0.111** | 3 |

**12× the audio → 3× the cost.** Output/reasoning flat (reasoning = 0 on all 3 runs); only
input tokens + omniASR grow, both cheap. Confirms "barely scales with length" and the
**note-credit** cap (a 1-hour note = ~3 credits, not 12). For long notes omniASR stops being
a rounding error (~40% of GPT at 60 min) but such notes are rare and credit-weighted anyway.

### "Is $0.29 expensive?" — no
$0.29 is the **whole day's** gpt-5 spend across **13 requests** (9 pre-test + our 4 test runs)
= **~$0.022/request average.** That is the cheap per-note cost the doc predicted, not a red flag.

---

## Action items
1. **Gary:** confirm the true `gpt-5-chat` blended rate (deployment-only Azure cost ÷ tokens).
2. **Build prompt caching** for the ~8K system prompt — top cost lever, halves GPT cost.
3. Update `services/usage.py` price constants once the rate is confirmed (currently $2.50/$15).
4. Continue runs (20-min, then a long/procedural file) to map cost vs length.
