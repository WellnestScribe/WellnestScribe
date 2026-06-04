# WellNest Scribe — Data Protection Compliance Summary

**Version:** 1.0 | **Date:** June 2026 | **Jurisdiction:** Jamaica & Barbados

This document maps WellNest Scribe's current controls against the requirements of the **Jamaica Data Protection Act 2020 (JA DPA)**, **Barbados Data Protection Act Cap. 308D (BB DPA)**, and the guidance delivered by the **Barbados Data Protection Commissioner** (transcript, June 2026). It identifies implemented controls, known gaps, and recommended next steps.

---

## 1. Data Classification

| Data Type | Classification | Notes |
|-----------|----------------|-------|
| Patient name, date of birth, ID number | Personal Data | Direct identifier — always handled as personal data |
| Clinical notes, diagnoses, medications | **Sensitive Personal Data** (JA DPA s.3, BB DPA s.2) | Health data is explicitly "special category" under both Acts |
| HIV status, mental health, reproductive health, substance use | **Highly Sensitive** | Attracts enhanced addendum in note generation; share-link generation blocked |
| Audio recordings of consultations | Sensitive Personal Data | Contains voice biometrics + health disclosure |
| Doctor identity, login logs | Personal Data | Internal operational data |

**Control implemented:** `is_sensitive` flag on `ScribeSession` — toggleable per encounter, with audit logging on access, flag changes, and blocked share attempts.

---

## 2. Lawful Basis for Processing

### Requirement
Both Acts require a lawful basis before processing personal data. For health data, the lawful basis must be explicit (JA DPA s.8; BB DPA s.7).

### Implemented
- Processing occurs within a doctor–patient relationship where the clinical purpose is the basis.
- Audio is processed solely to generate a clinical note — this is the stated and bounded purpose.

### Gap
- No formal **Privacy Notice / Patient-Facing Statement** exists within the application.
- The lawful basis has not been formally documented in a Data Register.

### Recommendation
- Add a brief patient-facing privacy notice (can be a QR code in the clinic or a printed card) explaining: what is recorded, who processes it, retention period, patient rights.
- Document the lawful basis in a Data Processing Register maintained by the clinic administrator.

---

## 3. Patient Consent for Recording

### Requirement (DPC Guidance — June 2026)
The Commissioner stated clearly:
- Patient consent is **required before recording** consultations.
- Consent must be **per-consultation**, not a single lifetime consent.
- Verbal consent is acceptable but **must be noted** in the system.
- The patient must be told: (a) what is being recorded, (b) who it is shared with, (c) the purpose.
- The patient must always be able to **decline or withdraw** consent.

### Implemented
- **Pre-recording consent modal** — shown before every new dictation or ambient recording session.
- The modal informs the doctor: recording will be processed by Microsoft Azure AI; audio is deleted after 30 days; patient may decline at any time.
- Doctor must check "I have received verbal consent" before the recording can start.
- Consent is required once per page-load (once per consultation visit to the recording screen).

### Gap
- Consent acknowledgment is **not yet persisted server-side** to the session record. The checkbox is client-only.
- There is no prompt to **document** the verbal consent in the patient's chart system.

### Recommendation
- POST a `consent_acknowledged_at` timestamp to the session save endpoint when the doctor ticks the consent checkbox. Store it on `ScribeSession`.
- Add a note in the generated clinical note template (e.g., "Patient verbal consent to AI-assisted recording obtained prior to consultation.") — toggleable via a setting.

---

## 4. Data Minimisation and Purpose Limitation

### Requirement
Collect only what is necessary for the stated purpose (JA DPA s.10; BB DPA s.9).

### Implemented
- Audio files are stored temporarily; not used beyond transcription + note generation.
- `AUTO_DELETE_AUDIO_DAYS = 30` — audio auto-deleted after 30 days.
- Patient name is optional on the record screen; the note is generated from the transcript alone.
- The AI prompt explicitly instructs the model not to invent details not stated in the transcript.

### Gap
- The `AUTO_DELETE_AUDIO_DAYS` setting exists but no scheduled task has been verified to enforce it in production.

### Recommendation
- Confirm a Celery beat task or cron job runs `delete_old_audio` on schedule and add a monitoring alert if it fails to run within 48 hours of its scheduled time.

---

## 5. Patient Rights

### Right to Know (Transparency)
- **Partial.** Consent modal informs patient at point of recording. No persistent patient-accessible privacy policy URL.

### Right of Access
- **Not implemented.** No patient portal or mechanism for a patient to request a copy of their data.

### Right to Erasure ("Right to be Forgotten")
- **Partial.** Audio is auto-deleted at 30 days. However, there is no endpoint allowing a patient (or their doctor on their behalf) to request immediate deletion of a session or note.

### Right to Rectification
- **Partial.** The doctor can edit the clinical note. Patient name is editable. No direct patient-facing correction mechanism.

### Recommendation
- Add an admin/doctor action to hard-delete a session (audio + note + metadata) on patient request, logging the erasure event to `audit.log`.
- Document the process for handling patient access requests in a procedure note.

---

## 6. Cross-Border Data Transfers

### Requirement (DPC Guidance — June 2026)
The Commissioner noted:
- Transfers to countries without equivalent data protection must be covered by **Standard Contractual Clauses (SCCs)** or equivalent safeguards.
- Azure's US data centers are subject to the **CLOUD Act**, meaning US law enforcement can compel disclosure. Clinics must be told this.
- Clinics should ask for safeguards documentation before signing up.

### Current Setup
- Azure OpenAI (US region) is used for note generation.
- Modal.com GPU (US) is used for ambient transcription.

### Implemented
- None formally.

### Gap
- No **Data Processing Agreement (DPA/BAA)** with Microsoft Azure or Modal confirmed in the codebase or documentation.
- No SCCs in place.
- No disclosure to clinic clients about Azure's US jurisdiction.

### Recommendation (Priority: High)
1. Confirm that WellNest has signed a **Microsoft Azure Data Processing Agreement** (available via Azure Portal > Privacy > DPA).
2. Confirm **Modal.com's DPA** is in place or evaluate whether ambient transcription can be moved to an EU/Caribbean region.
3. Add a clause in the **clinic onboarding agreement** disclosing Azure as a US-based processor and noting the CLOUD Act implication.
4. Consider enabling **Azure's Customer-Managed Keys** and using the `JM` / `BB` geography routing where available to limit data residency issues.

---

## 7. Security Safeguards

### Requirement
Both Acts require appropriate technical and organisational measures to protect personal data (JA DPA s.15; BB DPA s.14).

### Implemented
- HTTPS enforced at the application layer (Django `SECURE_SSL_REDIRECT` should be confirmed in production).
- CSRF protection active on all mutating endpoints.
- Django session authentication with idle timeout (`IDLE_TIMEOUT_MINUTES`).
- Sensitive encounter flag blocks share-link generation.
- `audit.log` captures sensitive session access, flag changes, blocked share attempts.
- Audio files stored outside the web root (path in `MEDIA_ROOT`).

### Gap
- `DEBUG = True` must never reach production — confirm `SCRIBE_ENV=production` check in `settings.py`.
- No confirmed encryption-at-rest for the database or audio files at the infrastructure level.
- No password complexity or 2FA enforcement for doctor accounts.

### Recommendation
- Enable database encryption-at-rest (Azure SQL TDE or equivalent).
- Add 2FA option to `accounts` app (TOTP via `django-otp`).
- Conduct a penetration test before clinic go-live.

---

## 8. Data Protection Impact Assessment (DPIA)

### Requirement (DPC Guidance — June 2026)
The Commissioner stated a DPIA is required when introducing new technology that processes sensitive personal data at scale.

### Implemented
- None formally.

### Gap
- No DPIA document exists.

### Recommendation
- Complete a DPIA before pilot deployment at any clinic. A DPIA template for Caribbean jurisdictions is available from the Barbados DPC. The DPIA must cover:
  - Purpose and description of processing
  - Necessity and proportionality assessment
  - Risk assessment (data breaches, AI errors, cross-border transfer)
  - Risk mitigation measures
  - Sign-off by a Data Protection Officer (or equivalent)

---

## 9. Breach Notification

### Requirement
Both Acts require notification to the supervisory authority (and in some cases the affected individuals) within a specified timeframe following a breach (JA DPA s.27; BB DPA s.24).

### Implemented
- None.

### Recommendation
- Draft a **Breach Response Procedure** covering: detection, assessment, 72-hour notification obligation to the ICO (JA) / DPC (BB), and patient notification criteria.
- Designate a responsible person for breach notification.

---

## 10. Sensitive Data — Enhanced Controls

### Implemented
- `is_sensitive` toggle per session (UI + backend).
- Share-link generation returns HTTP 403 for sensitive sessions; attempt is audit-logged.
- `SENSITIVE_ENCOUNTER_ADDENDUM` in the AI prompt ensures the note avoids naming the patient, uses appropriate language for HIV/mental health/substance-use disclosures, and appends a `[SENSITIVE]` disclaimer.
- `audit.log` records every access to a sensitive session review page (IP + user + timestamp).
- `[S]` badge on sensitive sessions in the history list.

### Gap
- No role-based access control limiting which staff can view sensitive sessions. Currently any authenticated user who knows the session URL can view it.

### Recommendation
- Restrict sensitive session access to the creating doctor only (or explicitly shared colleagues) via an ownership check in `ReviewView`.

---

## 11. AI-Generated Content Disclaimer

### Implemented
- Alert in `record.html`: "AI-generated drafts must be reviewed before clinical use."
- Generated notes carry a `[SENSITIVE]` addendum for sensitive encounters.
- The review screen requires the doctor to confirm/edit the note before it is considered final.

### Gap
- No permanent watermark or disclaimer embedded in the exported/copied note text itself.

### Recommendation
- Append a footer to all exported or copied notes: *"Generated by WellNest Scribe AI — clinician review required before use in medical records."*

---

## Summary Table

| Requirement | Status | Priority |
|-------------|--------|----------|
| Patient consent per-consultation | ✅ Modal implemented (client-side) | Persist server-side |
| Consent documented in session record | ⚠️ Client-only | Medium |
| Privacy notice / patient statement | ❌ Not implemented | High |
| Lawful basis documented | ❌ No data register | Medium |
| Sensitive data controls | ✅ Implemented | Complete |
| Cross-border transfer safeguards (Azure DPA/SCC) | ❌ Not confirmed | **High** |
| Audio auto-deletion (30 days) | ✅ Setting exists | Verify cron job |
| Patient right to erasure endpoint | ❌ Not implemented | High |
| DPIA | ❌ Not completed | **High** |
| Breach notification procedure | ❌ Not documented | High |
| Encryption at rest (DB + files) | ⚠️ Unconfirmed | High |
| 2FA for doctor accounts | ❌ Not implemented | Medium |
| AI-generated note disclaimer in exports | ⚠️ Partial | Medium |
| Sensitive session access control (owner-only) | ❌ Not implemented | Medium |

---

## Next Steps (Prioritised)

1. **Confirm Azure Data Processing Agreement** — required before any pilot with real patient data.
2. **Complete DPIA** — required before clinic deployment.
3. **Draft Privacy Notice** — patient-facing, one page, plain language.
4. **Persist consent acknowledgment** — add `consent_acknowledged_at` to `ScribeSession` and POST it on consent confirmation.
5. **Add session erasure endpoint** — for patient right-to-erasure requests.
6. **Restrict sensitive session access** to creating doctor.
7. **Draft Breach Response Procedure**.

---

*This document should be reviewed quarterly and updated when new features are added that affect personal data processing.*
