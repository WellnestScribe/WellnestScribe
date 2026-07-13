# WellNest — Subscription, Usage & Limits (how the whole system works, right now)

> The single reference for **how the subscription, note metering, and every user-facing
> limit/safeguard actually work in the current code.** Plain-language first, then the exact
> rules and the code that enforces them. Companion to `Control_Test_2026-07.md` (measured
> cost evidence) and the business plan (pricing rationale). Last updated 2026-07-12.

---

## 1. Plans — what a doctor/clinic buys

Per-clinician **scribe seat**, billed monthly (annual saves 10%). EMR is a bundled add-on
(+US$50); one shared EMR per facility. Institution = per-seat with invoice/PO.

| Plan | US$/mo | Monthly notes (credits) | For |
|---|---|---|---|
| Standard | 94 | **500** | everyday clinic (~15–20 patients/day) |
| Standard + EMR | 144 | 500 | scribe + lightweight EMR |
| Professional | 190 | **1,100** | high-volume / procedural (~25–40/day) |
| Professional + EMR | 240 | 1,100 | full stack, high volume |
| Institution | from 76/seat (min 10) | per contract | hospitals / authorities |

---

## 2. The unit: a "note-credit" (how the count goes up)

The topbar meter says **"notes left."** Internally that is a **note-credit**, and for a normal
note they are the same thing. The rule:

```
credits for one note = max(1, ceil(audio_minutes / 20))
```

| Recording length | Credits used |
|---|---|
| typed note / ≤ 20 min | **1** |
| 30 min | 2 |
| 1 hour | **3** |
| 2 hours | 6 |
| 3 hours (the auto-stop ceiling) | 9 |
| 4 hours | 12 |

- A short/typed note = **1**. The weighting only bites on unusually long recordings.
- **Regenerating, polishing, or editing the SAME note is free** — a credit is charged **per note (session)**, not per AI call.
- A **failed/errored** generation charges **0** (not counted).
- The meter is **per doctor** and **resets on the 1st** of each calendar month.

*Code: `note_credits_for_audio()` and `SECONDS_PER_CREDIT = 1200` in `apps/scribe/views.py`; the monthly sum is `_usage_summary()`.*

---

## 3. What the doctor sees — the meter

- Topbar **pill**: a ring + "N notes left". Colour: blue → **amber at 80%** → **red at 100%**.
- Click → popover: `used / cap` notes, notes remaining, reset date + days left, recording hours.
- Served by `GET /scribe/api/usage/` — **cached 60 s per doctor** (one cheap query), so it never taxes page loads.

*Code: `usage_summary_api()`, `_usage_summary()`, `_TIER_CAPS` in `apps/scribe/views.py`; pill in `templates/partials/topbar.html`.*

---

## 4. Everything that limits a user (the safeguards) — the important part

| Limit | Value | What it does | It NEVER… | Enforced in |
|---|---|---|---|---|
| **Monthly note cap** | 500 / 1,100 credits | Warn at ~80%, **soft-cap at 100%** | …blocks a note mid-visit | `_usage_summary` (display); soft — see §8 |
| **Per-note regenerate cap** | 12 | Stops runaway re-generation of one note | | `NOTE_GENERATE_CAP`, `_op_cap_response` |
| **Per-note grammar-polish cap** | 6 | Caps polish re-runs on one note | | `NOTE_POLISH_CAP` |
| **Per-note Magic-Edit cap** | 8 | Caps AI edits on one note | | `NOTE_MAGIC_EDIT_CAP` |
| **Recording length** | **auto-stop at 3 h** | Ends + **SAVES** the note; nudge at 90 min | …discard the recording | `AMBIENT_MAX_SECONDS` / `AMBIENT_WARN_SECONDS` |
| **Errored note** | not counted | A failed generation costs 0 credits | | `_usage_summary` (`.exclude(status="error")`) |
| **Billing suspended** (admin) | AI paused (HTTP 402) | Pauses note generation for a clinic | …gate EMR / patient records | `_scribe_billing_suspended`, `_BILLING_BLOCK_MSG` |
| **Demo lock** (admin kill-switch) | off / limited / locked | Throttles non-admins during public demos | …affect admins | `DemoLockdownMiddleware`, `PlatformControl` |

When a per-note cap is hit the API returns a friendly **HTTP 429** ("start a new session"), never a crash.

*Caps + `_op_cap_response()` + `_bump_op_count()` in `apps/scribe/views.py`; counters `generate_count` / `polish_count` / `magic_edit_count` on `ScribeSession` (`apps/scribe/models.py`).*

---

## 5. Anti-abuse: why a long recording can't be gamed

The credit weighting (§2) **is** the anti-abuse mechanism. Cramming 4 hours of many patients into
one recording costs **12 credits** — exactly the same as recording them as 12 separate notes. The
3-hour auto-stop then caps any single recording at 9 credits. So "one long note = one credit" is
impossible, and a forgotten recording can't run forever.

---

## 6. Edge-case register (every case + current status)

| # | Edge case | Behaviour | Status |
|---|---|---|---|
| 1 | 4-hour recording counted as 1 note | Now 12 credits | ✅ fixed (weighting) |
| 2 | Forgot to stop recording | Auto-stop at 3 h, saves note | ✅ fixed |
| 3 | Recording < 3 s | Rejected ("too short") | ✅ handled |
| 4 | Failed / errored note | Not counted | ✅ fixed |
| 5 | Regenerate many times | Free (1 credit/note) | ✅ |
| 6 | Uploaded long audio file | Credited by its audio length | ✅ |
| 7 | `duration_seconds` = 0 on uploads | Meter reads `timings.audio_seconds` | ✅ |
| 8 | **Cancel, then Record again** | Silently reuses last patient (`patientId` stays set) | ⏳ **fix: re-confirm patient** |
| 9 | Pause / "continue on auto" | Ambient has no pause; new recording = new note | ⏳ product decision |
| 10 | Browser tab closed mid-recording | Audio lost (not yet saved) | ⏳ roadmap |
| 11 | Month rollover | Credits reset on the 1st | ✅ |
| 12 | Tier upgrade mid-month | New cap applies; prorated (manual today) | ✅ policy |
| 13 | Hit the cap (100%) | Soft-cap: keep working, overage, never blocked | ✅ policy |

---

## 7. Doctor FAQ

- **What counts as a note?** One patient encounter (≤ 20 min). Longer recordings use a little more.
- **Is there a time limit?** Not a separate clock — time is built into notes (a 1-hour recording = 3 notes).
- **How many do I get?** Standard 500/month, Professional 1,100/month; resets monthly.
- **Can I record a 2-hour visit?** Yes — it's saved and uses 6 notes' worth; auto-stops at 3 hours.
- **Do edits/regenerations cost extra?** No — generating, regenerating, polishing and editing a note all count as **one** note.
- **What if a note fails?** It doesn't count against you.

---

## 8. At the cap: warning, overage, upgrade

- **~80%** → the meter nudges ("one of our busiest clinicians — Professional may fit you").
- **100%** → **soft cap**: the doctor keeps working; usage beyond the cap is **overage**, billed at month-end. **Never a hard stop in the middle of a visit.**
- **Upgrade** → **prorated**: pay only the difference for the remaining days of the month, cap jumps immediately. (Manual today — no payment processor; automatic once Stripe is added.)

---

## 9. Code map (verify against the codebase)

| Rule | File · symbol |
|---|---|
| Credit formula, monthly sum, tier caps, meter API | `apps/scribe/views.py` · `note_credits_for_audio`, `SECONDS_PER_CREDIT`, `_usage_summary`, `_TIER_CAPS`, `usage_summary_api` |
| Per-note AI-op caps | `apps/scribe/views.py` · `NOTE_GENERATE_CAP` (12), `NOTE_POLISH_CAP` (6), `NOTE_MAGIC_EDIT_CAP` (8), `_op_cap_response`, `_bump_op_count` |
| Per-note counters | `apps/scribe/models.py` · `ScribeSession.generate_count` / `polish_count` / `magic_edit_count` |
| Recording auto-stop / nudge | `templates/scribe/record.html` · `AMBIENT_MAX_SECONDS` (180 min), `AMBIENT_WARN_SECONDS` (90 min) |
| Billing suspend (never gates EMR) | `apps/scribe/views.py` · `_scribe_billing_suspended`, `_BILLING_BLOCK_MSG` |
| Demo kill-switch | `wellnest/middleware.py` · `DemoLockdownMiddleware` ; `apps/accounts/models.py` · `PlatformControl` |
| Meter pill (UI) | `templates/partials/topbar.html` (`wnUsagePill`) → `/scribe/api/usage/` |
| Cost telemetry (NOT a user limit) | `apps/scribe/models.py` · `ModelUsageLog` ; `apps/scribe/services/usage.py` |

---

## 10. Paste-to-AI audit prompt

Copy the block below to an AI **together with this file and the repo** whenever you want to
verify the system or plan the next safeguard:

> You are auditing WellNest's subscription/usage system. Attached: this spec
> (`Subscription_and_Usage_System.md`) and the codebase. Do this:
> 1. **Verify every limit in §4 and §9 against the actual code** — confirm the constants
>    (1 credit per 20 min; per-note caps 12/6/8; auto-stop 3 h / nudge 90 min; tier caps
>    500 / 1,100) and that they match what's deployed.
> 2. Confirm the invariants: **regenerating/polishing/editing a note does not add credits**,
>    **errored notes are not counted**, and **billing suspension never gates EMR/records**.
> 3. List any **drift** between this doc and the code (a constant changed, a rule missing).
> 4. List which **edge cases in §6 are still `roadmap`**, and for #8 (cancel→record) and #9
>    (resume) propose the smallest safe fix.
> 5. Suggest the **next safeguard** worth adding, with the exact file/function to change.
> Answer with: (a) verified ✅ / drifted ⚠️ per row, (b) the fixes, (c) the recommendation.
