# WellNest — Pilot-Readiness Audit

**Date:** 2026-07-15 · **Scope:** handing WellNest to an institution (nurses +
doctors) for a supervised pilot · **Author:** internal engineering review ·
**Status:** CONDITIONAL — a short, supervised pilot is achievable after the Tier-1
blockers below are closed; the system is **not** ready for unsupervised
institutional deployment.

This audit is deliberately blunt and pairs with `WellNest_Risk_Brief` (Malik's
adversarial review) and `docs/safety/diagnosis_extraction.md`. It is an
engineering readiness view, not legal advice.

---

## Verdict at a glance

| Dimension | State | Blocks pilot? |
|---|---|---|
| Clinical safety — note accuracy | ⚠️ Fabrication on Patois (model choice open) | **YES (Tier 1)** |
| Clinical safety — diagnosis coding | ✅ Hardened this cycle | No |
| Security & privacy (technical) | 🟡 Strong core, 2 gaps | Partly (Tier 1/2) |
| Legal / regulatory | 🔴 Not in place | **YES (Tier 1, non-code)** |
| Reliability & ops | 🟡 Works, fragile under load | Partly (Tier 2) |
| Data integrity | 🟡 Improved, 2 gaps | Partly (Tier 2) |
| Nurse/institution UX | 🟡 Usable, gaps for intake | No (Tier 3) |
| Observability / incident response | 🟡 Logs yes, alerting no | Partly (Tier 2) |

---

## Tier 1 — must close BEFORE any patient is recorded

**1. Note fabrication on non-standard (Patois) speech.** The core, unresolved
clinical risk. `gpt-5-mini` at minimal reasoning invented content on a real Patois
note (a seizure, a mis-attributed symptom duration, a food re-labelled as a
supplement, a guessed word "telemonitoring"). Mitigations applied this cycle:
reasoning raised to `low`, and the prompt now bans those exact failure modes.
**Action:** re-test on real Patois audio; if fabrication is not near-zero, run note
generation on the full `gpt-5-chat` model (one env var) and keep mini only for
low-stakes side tasks. **A pilot cannot start while the note invents clinical
events.** This is the single most important gate.

**2. Legal / regulatory standing (non-code, but hard gates).** From the risk brief:
OIC data-controller registration, company incorporation (personal liability until
then), a written data-processing agreement with the pilot institution, and
confirmation of cross-border transfer handling (no Azure region in Jamaica).
**None of these are code**, but a pilot that records real patients without them is
the cheapest catastrophic risk. Get written positions before go-live.

**3. Consent is not enforced server-side.** `consent_acknowledged_at` exists but is
a client-side checkbox; a session can be created without it. **Action:** reject
note generation unless consent is recorded on the session. Small change, closes a
DPA offence path.

---

## Tier 2 — close before the pilot scales past a handful of users

**4. Immutable audit trail.** `full_note` (AI draft) survives edits and `SessionEvent`
logs exist, but the log is mutable and there is no tamper-evident record of "what
the AI drafted vs what the clinician signed." For an institution this is the legal
defence if a clinician disputes a note. **Action:** append-only finalize record
(hash of AI draft + signed note + user + timestamp + edit distance).

**5. Reliability under concurrent nurse use.** The ambient-transcription job registry
is an in-memory dict, which forces `--workers 1 --threads 8`. That is fine for a
small clinic but is a single point of failure and a scaling ceiling. **Action:**
confirm the production start command is the gthread config (documented in
`docs/operations/server_and_gunicorn.md`); plan a shared job store (DB/Redis) before
multi-clinic scale.

**6. Audio retention actually enforced.** `AUTO_DELETE_AUDIO_DAYS=30` + a
`purge_audio` command exist, but no scheduled task is verified running it in
production. **Action:** schedule it (cron / Azure WebJob) and verify one run.

**7. Breach alerting (the 72-hour clock).** `SecurityEvent` logs critical events but
nothing notifies a human. A breach the DPA requires reporting in 72 h is useless if
no one sees the log. **Action:** alert on `critical` severity.

**8. Wrong-patient safeguard on QR transfer.** Add an explicit patient-identity
confirm step before a note binds to a record.

---

## Tier 3 — quality-of-life for the pilot, not blockers

**9. Nurse intake / check-in.** The scripted self-check-in (dropdown form +
read-aloud, no AI) digitises the paper triage form and cuts nurse data entry — a
strong institutional selling point. Planned, not built.

**10. Vitals/diabetes trend charts, mental-health screening (PHQ-9/GAD-7 + crisis
resources), onboarding tour.** All planned, all deterministic/no-AI, all improve the
nurse/doctor experience. Nice-to-have for the pilot.

**11. Automation-bias monitoring.** The risk brief's sharpest point: a near-zero edit
rate is a hazard signal, not a success metric. Track edit distance per clinician and
flag collapse toward zero.

---

## What is genuinely ready (credit where due)

- **Diagnosis coding safety** — negation/family/word-boundary guards, coding from the
  doctor's Assessment only, a separate ICD pass, and a cleanup command for legacy
  bad rows. Materially safer than most commercial scribes (`docs/safety/`).
- **PHI encryption at rest**, brute-force protection, idle-lock, QR/SSE transfer, ToS,
  and an intrusion-detection event model.
- **Role-based access** (membership roles), worklist/queue, encounter lifecycle with
  finalize lock, deduped longitudinal problem list / medications.
- **Measured unit economics** and a usage meter — the business side is quantified.

---

## Go / No-Go

- **No-go** for unsupervised institutional deployment today.
- **Conditional go** for a **small, supervised pilot** (one clinic, a few clinicians,
  every note reviewed and signed, patients consented) **once Tier 1 is closed** —
  specifically: the note-fabrication model decision made, consent enforced
  server-side, and the legal/registration positions written down.

**Recommended path:** resolve the mini-vs-chat note decision this week → enforce
consent server-side → confirm legal/registration with a Jamaican attorney → run a
2–4 week supervised pilot with edit-rate and incident monitoring → review Tier 2
before widening.
