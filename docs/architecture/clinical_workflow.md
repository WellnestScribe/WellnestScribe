# WellNest — Clinical Workflow (Nurse → Queue → Doctor → Auto-Encounter)

This document describes the coherent clinic flow WellNest models, the roles
involved, and how the scribe note becomes a structured EMR encounter
**automatically**. It mirrors how a Jamaican health‑centre docket flow works:
register → nurse takes vitals → the docket goes into the doctor's pile → the
doctor sees the patient → the docket is filed.

---

## 1. Roles

| Role | Does | Where |
|------|------|-------|
| **Nurse / Front desk** | Register/find patient, take chief complaint + vitals, send to the doctor's queue. No ROS/exam/signing. | **Front Desk** nav → Register / Find / Worklist & queue → **Intake** |
| **Doctor** | Picks the next patient from the queue, reads past notes, records the consult, finalizes. Lives on the scribe **New session** screen. | **Scribe → New session** |

Django superusers/staff bypass every EMR role gate (see
`OrganisationMembership._django_privileged`).

---

## 2. The flow

```
NURSE (Front Desk)
  Register patient  ─or─  Find patient (browse-all / card+table toggle)
    → Intake & vitals   (visit type + chief complaint + vitals)
    → "Send to queue"   → patient enters the doctor's waiting queue (appointment → triage)
  Re-opening Intake EDITS the same visit (no duplicate); "Already in queue" badge.

DOCTOR (Scribe → New session)
  Sees the Waiting queue  (carousel on desktop, list on mobile; FIFO ①②③)
    → tap a patient  → context bar shows demographics + nurse vitals
    → "Read past notes"  (skimmable cards, no AI)
    → consent → Record → generate note
    → "Mark reviewed" (finalize)
        • patient auto-pops off the queue (appointment → complete)
        • the note is AUTO-MERGED into the patient's encounter (see §4)

RETURN VISIT
  A patient the doctor already marked "Seen" cannot be re-added to the queue
  (the signed encounter is immutable). A return = a fresh Intake = new visit.
```

**Walk-in (no nurse):** the doctor records directly; the record modal searches
real patients and can quick-add a new one.

---

## 3. The queue

- **Source:** today's `emr.Appointment` rows with status `checked_in / triage / with_doctor`.
- **FIFO positions** `1..N` (first arrival first), reorderable with ↑/↓.
- **Real-time:** every surface polls `/emr/api/queue/` (~12 s), so any nurse
  change (reorder, patient left, new arrival, fresh vitals) shows up everywhere.
- **Consistent everywhere:** shared partial `templates/partials/_waiting_queue.html`
  on Intake / Advanced editor; a compact **carousel** on the record page
  (`d-none d-xl-block`) with a full‑width list on mobile (`d-xl-none`).
- **Remove with a reason** (Patient left / Sent home / …) so nobody is silently
  stranded; **Remove permanently** deletes the worklist row (note is kept);
  **Save worklist for the day** clears everyone still waiting (manual rollover;
  the queue is date-scoped so midnight also resets it).

Key endpoints (`apps/emr/`): `waiting_queue_api`, `appointment_status_view`,
`appointment_reorder_view`, `appointment_delete_view`, `worklist_close_day_view`.

---

## 4. Auto-merge: scribe note → EMR encounter (no AI)

When the doctor **finalizes** a scribe session that is linked to a patient
(`ScribeSession.patient`), `finalize_session_api` calls
`emr.services.scribe_import.materialize_encounter_from_session()`:

1. Reuses today's intake encounter for the patient (or creates one), never
   touching a **signed** encounter and never clobbering one already owned by a
   different scribe session.
2. Deterministically extracts from the note (via `build_scribe_import_bundle`,
   **regex/keyword only — no AI, no extra cost**):
   - **Encounter fields** — chief complaint, HPI, exam, assessment, plan, ROS,
     follow-up, sick leave, herbal remedies, visit type.
   - **Vitals** — BP, pulse, temp, SpO₂, glucose, weight, height… (auto-converts
     °F→°C, lb→kg, mg/dL→mmol/L and flags it).
   - **Diagnoses** — ICD-10 (e.g. I10 hypertension, E11.9 diabetes).
   - **Medications** — generic/brand, dose, route, frequency, duration.
3. Links the **scribe session + provider**, sets status **draft**, and saves.
4. Idempotent (re-finalizing never duplicates) and best-effort (a failure here
   never blocks finalize).

Result: the doctor's single action (record → finalize) produces both the note
**and** a structured, review-ready encounter in the patient's history. The
clinician reviews and **signs** it (signing locks it, records the signer).

---

## 5. Data model touch-points

| Concern | Model / field |
|---|---|
| Patient identity (docket) | `emr.Patient` + derived `mrn` (`WN000042`) |
| Scribe note ↔ patient | `scribe.ScribeSession.patient` → `emr.Patient` |
| Note ↔ encounter | `emr.Encounter.scribe_session` |
| Queue | `emr.Appointment.status` + `queue_number` |
| Nurse vitals → note context | `scribe.views._nurse_vitals_context()` injects measured vitals into note generation |

---

## 6. Guardrails / principles

- **Clinician-review-first:** every AI/extracted field is a draft; the doctor
  reviews and signs. Auto-merge produces a **draft**, never a signed record.
- **No AI where not needed:** registration, vitals, queue, and the scribe→encounter
  extraction are plain code — AI only runs for note generation.
- **Immutability:** a signed encounter is read-only; edits/returns create a new
  visit rather than altering history.
