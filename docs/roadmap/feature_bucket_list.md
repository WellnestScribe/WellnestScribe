# WellNest — Feature Bucket List (backlog / ideas)

> Running backlog of features + ideas discussed. Not committed work; a place to
> park and prioritise. Companion to `multispecialty_and_documents_architecture.md`
> and `performance_optimization_ideas.md`.

## Priority key
🔴 high value / soon · 🟡 medium · 🟢 nice-to-have / later

---

## EMR features doctors would love (vs Epic — but lightweight)
- 🔴 **Vitals & growth trend graphs** — BP / glucose / weight over time. Data is *already captured*; just needs charts. High value, low effort.
- 🔴 **Unified patient timeline** — one chronological stream of encounters, scribe notes, documents, labs. Makes it *feel* like a real EMR.
- 🔴 **Lab results + trends** — order/record labs, graph values over time. Pairs with the photo-upload path (see architecture doc).
- 🟡 **Managed problem list** — first-class longitudinal problems (not just per-encounter diagnoses).
- 🟡 **Chronic-disease recall / overdue lists** — "diabetics not seen in 3 months," HTN recall.
- 🟡 **Drug-interaction + allergy alerts at prescribing** — surface the existing drug-check inline in the note/prescription.
- 🟡 **Specialty note templates** — dental / radiology / lab (ties to the multispecialty config plan).
- 🟢 **e-signature / co-sign workflow** — supervised notes signed off by a senior.
- 🟢 **Immunisation schedule + recall** (peds), family & social history (structured).

## Documents / records (see architecture doc for the cost-safe design)
- 🟡 **Photo/document upload** — Azure Blob + metadata table (no document DB). Pennies/month.
- 🟢 **Historical-record OCR** — on-demand, additive, cheap vision model for indexing only. Never bulk.

## Messaging / reminders
- 🟡 **WhatsApp appointment reminders** — the JA channel. Cost + setup below.
- 🟢 **SMS fallback** (Twilio/local gateway) for patients without WhatsApp.
- ✅ Email reminders — **done** (`send_appointment_reminders`), pending SMTP creds.

### WhatsApp — cost & setup (ballpark; verify JA rates)
- **Channel:** Meta WhatsApp Business Platform (Cloud API), directly or via a BSP (Twilio / 360dialog / MessageBird). Twilio is the fastest to stand up.
- **Cost:** appointment reminders are **utility** messages. Meta made *service* conversations (inside the 24-h window) largely **free**; business-initiated **utility** messages cost per message/conversation, typically **~1–5 US cents each** depending on country. Via Twilio add ~**$0.005/msg** platform fee on top.
  - Realistic: a clinic sending ~500 reminders/month ≈ **$10–25/month total** across the platform. Negligible; pass-through or absorb.
- **Setup effort:** **Moderate.** Needs a Meta Business account + business verification + an approved message template ("Reminder: appointment at {clinic} on {date}…"). Verification/template approval takes a few days. App side ≈ **~1 day** once approved (a `send_whatsapp_reminder()` mirroring the email command).
- **Caveat:** Meta's pricing model shifts (moved toward per-message in 2025). **Confirm the current Jamaica utility rate** before quoting a clinic.

## Product / UX
- 🔴 **Onboarding tour** — first-time 4-step coach-marks on the dashboard (Yahoo-style bubbles). Self-contained build.
- 🟡 **Magic Edit cap** — include ~5 edits/note, warn on the 6th (don't block), route edits to a cheaper model (GPT-4o-mini/Nano ≈ $0.01 vs $0.03), log in the usage meter (T5). **Prevents a hidden AI cost.**
- 🟡 **Card restyle** — dashboard stat cards + chart summary cards to the theme's `ui-card.html` look; better dark-mode sizing.
- 🟢 Landing polish: "Built in Jamaica" badge, feature-cards → image cards.

## Cost / billing engineering (the money levers)
- 🔴 **T10 — pipeline flip (two-call → one-call GPT-5.4).** Halves the only real cost; makes the margins real. Needs one Patois quality check.
- 🔴 **T5 — usage metering** — log audio-min + input/output/reasoning tokens per note → true cost/note & cost/clinician; enforce warn-80% / soft-cap-100% (never block); smooth continuation.
- 🟡 **Multi-clinician billing** — per-clinician scribe seat + **one shared EMR add-on per facility** (see pricing). "Add a clinician at $94; EMR is one shared price for your whole clinic."
- 🟡 **Prompt caching + medium reasoning** on GPT-5.4 (further trims the LLM line, no quality loss).

## Performance (see performance_optimization_ideas.md)
- 🟡 **Streaming transcription** — note ready seconds after the visit (biggest UX win for long recordings).
- 🟢 **TensorRT FP16 for omniASR CTC encoder** — ~2–3× faster + cheaper GPU-seconds; validate Patois accuracy first.

## Moat / GTM (from incubator feedback, June 30 2026)
- 🔴 Lead with **Patois / Jamaican-English accuracy** + local compliance/residency (the defensible edge).
- 🟡 **Paid pilot** to validate willingness-to-pay (signed card > verbal yes). The in-app pilot survey feeds this.
- 🟡 Bottom-up via private practices + referral loop; compliance-certify early to unlock institutions.

## Engineering / testing (do properly at some point)
- 🔴 **Automated test suite + CI.** Django's `manage.py test` already runs the existing tests. Grow deterministic coverage of the safety-critical logic (diagnosis guards, RBAC `can_scribe`/`has_emr`, note-credit math, extraction) so a regression is caught before deploy. Add a **GitHub Actions job** that runs `manage.py test` on every push and blocks deploy if red (current workflow only deploys).
- 🟡 **Test-settings for SQLite** so `manage.py test` never needs CREATE-DATABASE perms on Aiven (fast, isolated). A `TESTING`/`--settings` flag pointing DATABASES at in-memory SQLite.
- 🟢 Later: a few Playwright end-to-end smoke tests for the critical flows (record → review → finalize; nurse blocked from scribe).
