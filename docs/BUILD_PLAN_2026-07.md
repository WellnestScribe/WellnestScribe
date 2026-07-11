# WellNest — Build Plan (July 2026)

> **Re-reference doc.** If context is lost/compacted, read this file first. It captures the
> full scope of the multi-part request from the user on 2026-07-10, the decisions made,
> and per-task specs + status. Update the **Status** lines as work completes.

## Source of the request
User asked (voice, paraphrased) to pull several purchased admin theme pages
(`c:\xampp\htdocs\WellnestScribe\admin\*.html`) into the real app, plus subscription/limits
work, landing-page polish, cost-doc analysis, and EMR gap advice. Three cost PDFs were shared.

Theme assets already vendored in the app: **FullCalendar** at `static/vendor/fullcalendar/`
(main.min.css / main.min.js). Images for landing at `temp images/` →
`landing page doctor looking at laptop.jpg`, `surgery tech.jpg`.

---

## ✅ Already done this session (audio upload fix — DOCUMENTED)
**Problem:** uploading a 1h26m / 159 MB MP3 → `Modal omniASR HTTP 413: File exceeds 100 MB`.
Root cause: the 100 MB cap is **ours** (`LIGHTNING_SPEECH_MAX_FILE_MB`, default 100, in
`deploy/lightning_speech_api/app.py:29`); Modal reads the whole upload into RAM. A long/high-bitrate
file exceeds it. (Browser recordings were separately being inflated by a webm→WAV conversion.)

**Fix (in `apps/scribe/services/triage.py`):**
- New `_transcode_to_opus16k(src)` — PyAV (bundles ffmpeg, cross-platform, streams frame-by-frame,
  low memory) → **16 kHz mono Opus @ 32 kbps**. Verified: **159 MB → 19.6 MB, ~50s, full 86.6 min,
  valid, mono**. 16 kHz mono is omniASR's native rate → **zero ASR quality loss**.
- Wired into `transcribe_modal_omni` **and** `transcribe_modal_mms`: transcode when file is a browser
  format (webm/ogg/opus) **or > 40 MB**; small compatible files sent raw. WAV path kept as fallback.
- `av==17.0.1` pinned in `requirements.txt` (was missing — without it the server silently falls back
  to WAV and the fix fails in prod). **Deploy: `pip install -r requirements.txt`.**
- Sizing at 32 kbps ≈ 13.6 MB/hr → 3 h ≈ 41 MB, 6 h ≈ 82 MB. Headroom to ~7 h under the cap.
- Future: chunking for >7 h sessions; optionally raise `LIGHTNING_SPEECH_MAX_FILE_MB` on Modal.

---

## Decision 1 — Which cost document is most accurate?
Three PDFs: **Business Model** (session-based, Modal L4, $0.021/note, 300 sessions + 35 JMD overage),
**Cost & Pricing** (measured: real 15-min note = **$0.04** omniASR transcription; verified GPT-5.4
prices), **Pricing/Cost & Market-Readiness** (newest; reconciles the other two).

**Verdict:**
- **Most authoritative = "Pricing, Cost & Market-Readiness"** — newest, explicitly reconciles the
  other two, treats the measured Cost doc as ground truth, and corrects the Business Model's
  optimism. Use **its decisions**.
- **Most accurate unit costs = "Cost & Pricing"** — it has the one hard measured anchor
  (15-min note = $0.04 omniASR transcription, ~10× realtime, effective Modal ~$1.22/hr).
- **"Business Model" is outdated on the cost model** — flat per-session pricing ("$40 cost / 57%
  margin") hides that margin collapses on heavy/anesthesia users. Its infra breakdown is still useful
  reference, but do **not** price per-session or per-note from it.
- **New cost line no doc captured:** server-side Opus transcode now costs ~50s CPU per ~90-min upload.
  Negligible per note, but note it for concurrency at scale (runs in the async job, streams, low mem).

## Decision 2 — Subscription mechanism (answers the user's questions directly)
- **Meter on audio-minutes, NOT note count.** A 5-min consult and a 90-min procedure both = "1 note"
  but cost ~10× differently. Drop the customer-facing **500-note cap**; market **"unlimited notes."**
- **The audio-hour allowance is the real limit** (Standard ≈ 80–120 audio-hrs/mo).
- **"Does a continuation/resume count as another note?"** → It doesn't matter, because we bill
  **audio-minutes, not notes.** A resumed session simply **adds to the same audio meter**. So track
  **cumulative audio-seconds per session AND per billing period.**
- **"Restrict runaway resume" (someone resumes and leaves it running an hour):**
  - **Per-session hard cap** — auto-stop a single recording at **3 h (Standard) / 5 h (Procedural)**.
  - **Silence auto-stop** — end after N minutes of silence.
  - These bound a single runaway; the audio-hour meter bounds the month.
- **Never hard-block a note in progress** (clinical/legal safety). Let the current note finish, then:
  warn at **80%**, **soft-cap at 100%** (upgrade prompt + flag account, keep working).
- **Records are never blocked for non-payment** — only the AI scribe is suspended (already built).
- **Tiers (reconciled, JMD @ ~158/USD):**
  | Tier | JMD/mo | ~USD | Allowance |
  |---|---|---|---|
  | Lite (optional) | 10,000 | 63 | unlimited notes · ~40 audio-hr · Mini-only |
  | **Standard** | 15,000 | 94 | unlimited notes · ~120 audio-hr (Mini routing) · ~5 edits/note |
  | Procedural | 30,000 | 190 | unlimited notes · ~250 audio-hr · per-note ≤5 h |
  | Scribe + EMR | 20,000 | 127 | Standard + lightweight EMR |
  | Institution | from 12,000/seat | 76 | per-seat, 20% off 5+ |
- **Allowance UX:** no visible meter until ~80%; then a gentle, complimentary banner
  ("you're one of our most active clinicians — Procedural may fit you"); never a mid-consult popup;
  full usage lives in the admin/billing dashboard.

## Decision 3 — Usage metering (the "gating item" per the docs)
Per note, log: cold/warm, GPU active seconds, audio minutes, **resume segments**, and per GPT call
the **model tier (5.4/mini/nano) + input + output + reasoning tokens + edit count** → computed
total cost. Allocate monthly platform cost (DB + hosting + storage) across active clinicians →
true cost/note and cost/clinician. Model: `scribe.UsageRecord` (or extend ScribeSession).

---

## Build tasks (execution order + specs)

### T1 — Appointments calendar (FLAGSHIP)  ·  Status: NOT STARTED
Template: `admin/apps-calendar-schedule.html` (FullCalendar; assets already at `static/vendor/fullcalendar/`).
- New page **"Appointments"** under Front Desk / near "Find patient".
- Month/Week/Day/List views. Click a slot → **search patient** (reuse `/emr/api/patient-search/`) →
  create an `emr.Appointment` at that datetime. Existing model: `Appointment(patient, scheduled_for,
  status, encounter_type, ...)` + existing `appointment_create_view`, `appointment_status_view`.
- Event click → popover: patient name, **phone (`patient.phone_primary`)**, type, status; buttons
  "Open chart", "Start triage" (`emr:triage`), "Call" (`tel:` link), reschedule/cancel.
- Backend: `appointments_calendar_view` (page) + `appointments_feed_api` (JSON events for a date
  range) + reuse create/status/delete. Scope to org. FullCalendar `events` from the feed.
- **Email reminders:** `send_appointment_reminders` management command (run daily via cron/Task
  Scheduler) → email patients with an appointment tomorrow/today (Django email; needs SMTP settings).
  Also power the sidebar bubble (T7).
- Nurse view: "today's appointments" list with **click-to-call phone** so they can ring patients.

### T2 — Invoice-style print for prescriptions & referrals  ·  Status: NOT STARTED
Template: `admin/apps-invoice-details.html` (uses `window.print()` + `d-print-none` + print CSS).
- Existing views: `emr:prescription_print`, `emr:referral_print`. Make their templates render like the
  clean invoice: clinic header (name/address/phone from Organisation), patient block, itemised table
  (meds: drug, dose, route, freq, duration, qty; referral: reason, to-whom, notes), footer/signature.
- Add a dedicated print stylesheet (`@media print`) + a "Print" button (`window.print()`), `d-print-none`
  on nav/buttons. Also usable for a future patient invoice/receipt.

### T3 — Sign-in / Sign-up redesign  ·  Status: ✅ DONE (2026-07-10)
Done: added fade-in + brand-accent to `.auth-card` (wellnest.css), softer inputs/button; added
**"Forgot password?"** link on sign-in → new `accounts:password_help` page (admin-reset guidance,
no SMTP needed, since accounts are admin-provisioned via `set_password_api`). App already had no
blue full-bleed bg and no social buttons. Verified all 3 auth pages render 200.
Original spec below:
Template: `admin/auth-signup2.html` / `auth-signin2.html`. Current app: `templates/accounts/signin.html`
(38 ln), `signup.html` (69 ln).
- Keep the **card/form shape + fade-in effect**. **Remove the blue full-bleed background** (keep app
  theme bg). Put the **WellNest logo** at top. Remove **Google/Facebook/GitHub** social buttons.
- Keep **Reset password** link + email field styling. Login by **username OR email** + password.
- Must look neat/professional (not "AI-generated").

### T4 — Subscription & data page (pricing/limits)  ·  Status: NOT STARTED
Template: `admin/pages-pricing.html`. Surface under **user icon → "Subscription & data"**
(existing `subscription_view` / `my_data_export`). Show: current facility, tier, **audio-hours used /
allowance**, features, limits (from Decision 2), upgrade CTA, data export. Pull live usage from T5.

### T5 — Usage metering + guardrails (GATING)  ·  Status: NOT STARTED
Implements Decision 3. Model to store per-session audio-seconds + token/cost breakdown; aggregate to
monthly per-clinician + per-org. Enforce: per-session auto-stop (3h/5h), silence auto-stop, warn 80%,
soft-cap 100% (never block in progress). Surfaces in T4 + admin/billing dashboard.

### T6 — Landing page polish  ·  Status: NOT STARTED
Add tasteful animations (fade/slide on scroll — keep it subtle) and the two `temp images/` photos
(`landing page doctor looking at laptop.jpg`, `surgery tech.jpg`). Copy them into `static/img/` first.
Current landing template: find in `templates/` (likely `landing.html` / home). Don't overdo motion.

### T7 — Appointment reminder bubble  ·  Status: NOT STARTED
Small orange badge/bubble on the sidebar nav (Appointments item) showing count of patients due
today/soon. Poll a lightweight `appointments_due_api`. Ties into T1.

### T8 — Missing lightweight-EMR features (advisory + optional build)  ·  Status: ADVISORY GIVEN
See "EMR gap analysis" below.

---

## EMR gap analysis — likely-missing features vs. a typical EMR
(Have: Patient, Encounter, Diagnosis, Medication, Vital, Allergy, Immunisation, Referral, Appointment,
AuditLog, scribe notes, prescription/referral print, drug-interaction check.)

**High value, likely missing:**
1. **Lab / investigation results** — order + record results + trend over time (only an image/lab stub today).
2. **Managed problem list** — first-class longitudinal problems (currently derived from diagnoses).
3. **Document/attachment management** — scanned paper dockets as **tagged flat images** (type + date +
   title; capture-on-visit, "mark as scanned" flag). *Do NOT bulk-OCR* (handwriting → dose errors).
4. **Recall / chronic-disease follow-up** — diabetes/HTN recall lists; overdue-visit flags.
5. **Vitals trend graphs** — BP/glucose/weight over time (data already captured).
6. **Growth charts** (pediatrics) — percentiles fields already exist; no chart yet.
7. **Family & social history** — structured fields.
8. **Encounter templates** — antenatal, well-child, chronic review.
9. **Patient timeline** — one chronological stream interleaving encounters, scribe notes, docs, labs.
10. **NHF / insurance claim** support (NHF card fields exist; no claim workflow).
11. **No-show tracking** + appointment reminders (T1/T7 start this).
12. **Patient-facing SMS/WhatsApp reminders** (WhatsApp is the Jamaica channel).

---

## Open items / to confirm with user
- SMTP/email provider for reminders (T1) — needs config before reminders actually send.
- Which tier numbers are final (Decision 2 uses the reconciled readiness-doc set).
- Whether to build T8 EMR gaps now or after T1–T7.
