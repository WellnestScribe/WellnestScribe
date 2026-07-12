# Data, Privacy & Security Policy

How WellNest protects patient data and stays aligned with Jamaica's Data
Protection Act (2020). Team reference; shareable with customers.

---

## 1. PHI at rest

Sensitive clinical text is stored **encrypted** (Fernet, AES-128-CBC + HMAC-SHA256)
via `EncryptedTextField` / `EncryptedCharField` on the scribe models — patient
name, identifier, chief complaint, transcript, and all SOAP note fields.
Decryption is transparent through the ORM; the key lives in `FIELD_ENCRYPTION_KEY`.

Raw audio is **not retained** after a note is generated — only the structured
note is kept (data minimisation).

## 2. Access control

- **Roles** (per user + per facility) drive what each person can do — doctor,
  nurse, receptionist, scribe, radiologist, pharmacist, lab tech, admin.
- Data is **organisation-scoped**: a user only sees patients in their facility.
- Superusers/staff bypass gates (platform owners).

## 3. Audit

- `emr.AuditLog` records who viewed/edited each record and when (per facility).
- `SecurityAuditMiddleware` watches for rapid access, impossible travel, and
  endpoint probing, alerting `SECURITY_ALERT_EMAIL`.
- Sensitive encounters (HIV, mental health, reproductive, substance use) get
  enhanced view-level audit logging and blocked share links.

## 4. Sessions & device safety

- Session cookies expire after 4 h.
- **Idle screen lock** after `IDLE_LOCK_MINUTES` (password re-entry to unlock),
  force sign-out after a further 10 min.
- Brute-force lockout (django-axes): 5 failures → 15-min cool-off.

## 5. Consent

- Verbal patient consent is captured **before** recording (timestamped) — valid
  under the DPA. A suggested consent script is shown to the clinician.

## 6. Data ownership, portability & retention

- Customers own their data. Full **JSON export** is always available per facility.
- On billing suspension the export is auto-emailed; data is retained for a
  window (default 60–90 days) before purge. See **Billing & Offboarding Policy**.
- Right to erasure: a session (with audio + note + events) can be permanently
  deleted on request.

## 7. Clinician-review-first

Every AI-generated or auto-extracted field is a **draft** the clinician confirms
or edits before it is saved/signed. WellNest aids documentation; it does not
make diagnostic or treatment decisions.
