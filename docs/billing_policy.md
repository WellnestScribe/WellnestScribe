# Billing, Subscriptions & Offboarding Policy

How WellNest is priced, how non-payment is handled, and what happens to a
customer's data if they leave. Written for the team; safe to share with
customers who ask.

---

## 1. Pricing model

The **AI scribe** is the cost driver (transcription + LLM) and is priced **per
clinician who dictates**. The **EMR** (records, queue, intake, prescriptions) is
shared facility infrastructure and does **not** consume AI, so support roles
(nurse, receptionist, lab, pharmacy) are included per facility.

| Plan | Priced per | For | Guide price |
|------|-----------|-----|-------------|
| **Scribe only** | per provider | solo doctor, AI notes only | ~US$94 / provider / mo |
| **Practice (Scribe + EMR)** | per provider + facility | clinic with doctors + support staff | provider seats + EMR |
| **EMR only** | per facility | nurse/front-desk-run clinic, no AI | flat facility fee |
| **Trial** | — | evaluation | free |

A **1 doctor + 1 nurse** practice = one provider seat (the nurse is a free
support seat). A **3-doctor** practice = 3 provider seats.

Managed by admins under **Billing** (manual — no payment processor yet). Fields
per facility: tier, status, provider seats, paid-through date, monthly amount,
notes.

---

## 2. Core principle — records are never held hostage

**Access to patient clinical records is NEVER blocked for non-payment.** This is
a patient-safety and continuity-of-care commitment. Non-payment pauses the
*paid value-add* (AI note generation), not the record.

Enforcement in code: `Organisation.scribe_enabled` is `False` only when status
is `suspended`/`cancelled`; the scribe generate endpoints return a clear
"subscription paused, records still available" message. EMR record views are
never gated on billing.

---

## 3. Non-payment → grace → offboarding

Graceful degradation, not a lockout. Timeline (private clinic):

| Stage | When | What happens |
|-------|------|--------------|
| **Due** | Day 0 | Invoice + reminder. Full access. |
| **Past due** | Day 1–14 | `past_due`. **Full access** + escalating reminders (email + in-app banner). |
| **Final notice** | Day 15–29 | Still accessible; "final notice" banners. |
| **Suspended** | Day 30 | Features off (no new AI notes). **Records still viewable + exportable.** Data auto-exported and emailed to the account owner. |
| **Retention window** | Day 30–90 | Data kept on our side; customer can still request a re-download. "Download now" warning ~Day 80. |
| **Purge** | Day 90 | Data permanently deleted after final notice. |

**Grace period by customer type (Jamaican context — manual bank transfers,
month-based budgeting, slow institutional cycles):**

- **Private clinic / solo doctor:** **21–30 days** past due before suspension.
- **Government / hospital / institution:** **45–60 days** (their disbursement
  cycles are genuinely slow).

Be generous — locking out a clinic mid-care is high-stakes and churns
honest-but-late payers.

---

## 4. Data portability & exit

- **Export is always available** (Users & Orgs → facility → Export) — full JSON:
  patients, encounters, diagnoses, medications, vitals, allergies.
- On suspension, the export is **auto-emailed** to the account owner so they are
  never stranded.
- We **retain** the data for the retention window (default 60–90 days) after
  cutoff before purging, so a bounced email or wrong recipient doesn't lose it.

---

## 5. Manual override (always)

Whatever a future payment processor decides, an admin can **force a facility to
Active with one click**. This protects against processor mistakes — the whole
point of keeping enforcement soft and manual override on.

---

## 6. To formalise in the Terms of Service

- Grace-period length by plan.
- What is suspended vs. what stays available at cutoff.
- Data-retention window post-cutoff and the purge date.
- That export is always available and auto-sent on suspension.
