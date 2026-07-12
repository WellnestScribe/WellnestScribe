# WellNest Scribe — Security Architecture

*Last updated: June 2026. Update this document when controls are added or changed.*

---

## Table of Contents

1. [Threat Model Summary](#1-threat-model-summary)
2. [Authentication & Session Security](#2-authentication--session-security)
   - [Compromised password / remote login](#threat-compromised-password--unauthorized-remote-login)
   - [Family member on unlocked device](#threat-family-member-or-child-accessing-an-unlocked-device)
   - [MFA — planned](#multi-factor-authentication-mfa--planned)
3. [PHI Field Encryption](#3-phi-field-encryption-application-layer)
   - [What is encrypted](#what-is-encrypted)
   - [What type of encryption is used](#what-type-of-encryption-is-used)
   - [How the encryption key works](#how-the-encryption-key-works)
   - [Key management](#key-management)
   - [Encrypt existing rows](#encrypt-existing-rows-run-once-after-configuring-the-key)
   - [Graceful fallback](#graceful-fallback)
   - [What remains unencrypted](#what-remains-unencrypted-and-why)
   - [Key rotation](#key-rotation-procedure-future)
4. [Transport Security](#4-transport-security)
5. [Intrusion Detection](#5-intrusion-detection-application-layer)
6. [Data Sharing & QR Transfer](#6-data-sharing--qr-transfer)
7. [Sensitive Encounter Flag](#7-sensitive-encounter-flag)
8. [Audit Logging](#8-audit-logging)
9. [Role-Based Access Control](#9-role-based-access-control)
10. [Audio File Security](#10-audio-file-security)
11. [Database Security](#11-database-security)
12. [Security Roadmap (TODO)](#12-todo--security-roadmap)
13. [Caribbean DPA Compliance Checklist](#13-caribbean-data-protection-compliance-checklist)

---

## 1. Threat Model Summary

WellNest Scribe processes Protected Health Information (PHI): patient names, consultation
recordings, clinical transcripts, and SOAP notes.  The platform is designed for use in
Caribbean healthcare facilities subject to:

- **Jamaica Data Protection Act 2020** (in force August 2023)
- **Trinidad & Tobago Data Protection Act 2011**
- **Barbados Data Protection Act 2019**
- Caribbean medical ethics codes (WMA / GMC-equivalent)

Primary threats addressed:

| Threat | Control |
|---|---|
| Credential brute-force | django-axes lockout after 5 failures |
| Database breach (stolen credentials) | Application-layer field encryption (Fernet/AES-256) |
| Session hijack / family access | Idle screen lock, short session lifetime |
| Insider / mass data extraction | Rapid-access detection, audit logging |
| Account takeover | Impossible-travel detection, last-login IP display |
| Phishing / session fixation | HTTPS-only, HSTS, SameSite cookies |
| Clickjacking | X-Frame-Options DENY |

---

## 2. Authentication & Session Security

| Control | Setting / value |
|---|---|
| Password hashing | Django default: PBKDF2-SHA256 with 870,000 iterations |
| Brute-force lockout | 5 failures → 15-minute lockout (django-axes) |
| Session cookie | HttpOnly, SameSite=Lax, Secure in production |
| Session lifetime | 4 hours (rolling; resets on activity) |
| Idle screen lock | 15 minutes of inactivity → password re-entry required |
| Forced sign-out | 10 minutes after lock screen if still unlocked |
| CSRF protection | Django CsrfViewMiddleware on all POST/PATCH/DELETE |

### Threat: Compromised password / unauthorized remote login

If a doctor's password is stolen or guessed and someone logs in from an external device:

- **Impossible travel detection** fires an email alert to `SECURITY_ALERT_EMAIL` if the
  same account is seen from two different network subnets (/8) within 30 minutes. The
  alert is immediate — you do not have to wait for a scheduled audit.
- **Last login IP** is displayed in the UI on every login. The doctor sees their previous
  session's IP on their next sign-in. An unrecognised IP is a visible signal of
  unauthorized access.
- **Brute-force lockout** (django-axes) means a password cannot be guessed by automated
  tools — the account locks for 15 minutes after 5 wrong attempts.

**Current gap:** None of the above stops someone who already has the correct password.
The fix is MFA (see Section 12 TODO). With MFA enabled, a stolen password alone
is insufficient — the attacker also needs the doctor's physical phone to generate the
second factor code.

### Threat: Family member or child accessing an unlocked device

Doctors may leave a phone or tablet unattended at home with WellNest still open.
The **idle screen lock** is the primary control:

1. After **15 minutes** of no interaction, a full-screen lock overlay covers the entire
   UI. All patient data underneath is hidden — not just blurred.
2. The lock screen requires the doctor's password to dismiss. Without it, nothing
   in the application is visible.
3. If the password is not entered within **10 minutes** of the lock appearing, the
   session is fully terminated. The next person to pick up the device sees only the
   login page.

This means the maximum exposure window on an unattended device is **25 minutes** from
the moment the doctor puts it down. After that, a full login (and soon: a second
factor) is required.

**What the idle lock does not protect against:** a family member actively using the
device within the 15-minute window. This is a human/policy control — facilities should
include acceptable use guidance in staff onboarding (do not leave sessions open on
shared or home devices).

### Multi-Factor Authentication (MFA) — planned

MFA is not yet live but is the next planned security addition. The intended
implementation uses **TOTP** (Time-based One-Time Password) — the same rotating
6-digit code system used by Microsoft Authenticator and Google Authenticator.

**Cost:** Free. TOTP is an open standard (RFC 6238). Microsoft Authenticator is a
free app. The Django library (`django-two-factor-auth`) is open-source.
No per-user fees, no per-login fees. The only paid MFA option is SMS OTP
(costs per text message sent) — WellNest will use TOTP to avoid this cost.

When live, the login flow will be:
1. Enter username + password (as now)
2. Open Microsoft Authenticator (or Google Authenticator), enter the 6-digit code
3. Access granted

A stolen password without the doctor's physical phone will not be sufficient to log in.

---

## 3. PHI Field Encryption (Application Layer)

### What is encrypted

All patient-identifiable fields are encrypted in the database using Fernet symmetric
encryption (AES-128-CBC + HMAC-SHA256) before being written.

**ScribeSession model:**
- `title`, `chief_complaint`, `patient_name`, `patient_identifier`
- `transcript`, `raw_transcript`

**SOAPNote model:**
- `visit_summary`, `subjective`, `objective`, `assessment`, `plan`
- `narrative`, `full_note`, `edited_note`

### What type of encryption is used

WellNest uses **Fernet** — a standard symmetric encryption format from Python's
`cryptography` library.  Under the hood it combines:

| Component | Algorithm | Purpose |
|---|---|---|
| Encryption | AES-128-CBC | Scrambles the data so it cannot be read without the key |
| Integrity check | HMAC-SHA256 | Detects any tampering with the encrypted data |
| Key size | 256-bit (32 bytes) | Industry-standard strength |
| Format | URL-safe base64 | Stores safely as a text string in any database column |

**Why AES?** AES (Advanced Encryption Standard) is the same algorithm used by governments,
banks, and hospitals worldwide. It is the NIST-approved standard for protecting sensitive
data at rest.

**Why Fernet specifically?** Fernet is a high-level wrapper that prevents common
implementation mistakes (e.g., using the same IV twice, skipping integrity checks).
Every encrypted value starts with `gAAAAAB` — if you ever see this in the database,
encryption is active.

### How the encryption key works

**Plain-English explanation:**

The `FIELD_ENCRYPTION_KEY` is a 44-character random string — think of it as a
master password for the database.  Here is the full lifecycle:

```
Generate key once
  ↓  (copy the printed string — that IS the key)
Save it in a password manager
  ↓
Set it as FIELD_ENCRYPTION_KEY in Azure App Service config
  ↓
App reads the key from the environment every time it starts
  ↓
Doctor saves a patient note → app encrypts it before writing to DB
  ↓  (DB stores gAAAAABn8Kx2hJmP... — unreadable gibberish)
Doctor opens the note → app decrypts it on the way out → readable text
```

**The key never touches the database.** It lives only in Azure App Service
Application Settings (the environment variable config). This means:

- If someone steals the database, they get `gAAAAAB...` strings — useless.
- Only someone who has the key can read the data — that is the entire point.

**What happens without the key:**

| Situation | Result |
|---|---|
| Key not set, no encrypted rows | App works normally; data saved as plaintext |
| Key not set, rows already encrypted | App still runs; encrypted rows display as `gAAAAAB...` gibberish |
| Key is wrong (typo / different key) | Same as above — silent failure, no crash |
| Key is correct | All PHI fields encrypt on write, decrypt on read transparently |

**Generating the key** — run this once on any machine with Python:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This command does nothing except print a random string to the screen.
It does not connect to any database or change any data.
Copy the output and treat it like a root password — back it up before you use it.

**The key is not server-specific.** The same key works on Azure, on a local machine,
on any environment — as long as they all connect to the same database.
If you share a database between local dev and production, all environments need the
same key in their `.env` or they will see ciphertext.

### Key management

- Key stored in `FIELD_ENCRYPTION_KEY` environment variable (Azure App Service
  Application Settings — not in the database, not in code).
- Fernet format: 32-byte URL-safe base64-encoded key.

### Generate a key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set this value as `FIELD_ENCRYPTION_KEY` in `.env` or Azure App Service config.

### Encrypt existing rows (run once after configuring the key)

```bash
python manage.py encrypt_existing_phi
```

Safe to run multiple times — already-encrypted rows are decrypted then re-encrypted.

### Graceful fallback

If `FIELD_ENCRYPTION_KEY` is absent or misconfigured, the fields behave exactly like
plain Django TextFields. Existing data remains readable. This prevents a misconfiguration
from causing data loss on first deploy.

### What remains unencrypted (and why)

| Field | Reason |
|---|---|
| `patient_gender` | Single-character code, not identifying alone |
| `active_conditions` | Short code list (`dm,htn`), used for DB filtering |
| `status`, `note_format` | Workflow metadata, needed for queryset filtering |
| `is_sensitive` | Boolean, must be filterable for security checks |
| `flags` (JSON) | Structured clinical flags, low direct-identity risk |
| All `DoctorProfile` fields | Doctor preferences only, no patient PHI |

### Key rotation procedure (future)

1. Set `FIELD_ENCRYPTION_KEY_NEW=<new key>` alongside the old key.
2. Run a rotation management command (TODO — not yet built).
3. Swap `FIELD_ENCRYPTION_KEY` to the new value.
4. Remove `FIELD_ENCRYPTION_KEY_NEW`.

---

## 4. Transport Security

| Control | Detail |
|---|---|
| TLS enforcement | `SECURE_SSL_REDIRECT = True` in production |
| HSTS | 1-year max-age, includeSubdomains, preload |
| Minimum TLS | Configured at Azure App Service level (TLS 1.2+) |
| Certificate | Azure-managed or custom domain certificate |

---

## 5. Intrusion Detection (Application Layer)

`wellnest/middleware.py` — `SecurityAuditMiddleware` — monitors every request:

| Pattern | Threshold | Action |
|---|---|---|
| Rapid access | >60 authenticated requests/60s from one IP | Audit log + email alert |
| Impossible travel | Same user, different /8 subnet within 30 min | Audit log + email alert |
| Error probing | >10 × 403/401 from same IP within 5 min | Audit log + email alert |

Email alerts are rate-limited to one per pattern-type per IP per hour.

Configure the alert recipient: `SECURITY_ALERT_EMAIL=you@facility.com` in `.env`.

### Infrastructure layer (Azure)

- **Azure Defender for Cloud** (paid) — monitors App Service and database for known
  attack signatures. Recommended to enable for production.
- **Azure DDoS Protection Basic** — free, automatically applied.
- **Azure MySQL / PostgreSQL Firewall** — restrict to App Service outbound IP only.

---

## 6. Data Sharing & QR Transfer

### WhatsApp sharing — REMOVED

WhatsApp sharing was removed in June 2026 because it transmitted note text (PHI) outside
the platform to a third-party service.  There is no exception for clinical urgency.

### QR code transfer (authenticated, no PHI in code)

The QR code now encodes a short-lived claim token that points to `/scribe/claim/<token>/`.

- The claim URL **requires authentication** — the scanning device must be logged in to
  the same WellNest account.
- Scanning the QR fires an SSE (Server-Sent Events) notification to the PC browser.
- The PC navigates to the session; **no patient data is transmitted to the phone**.
- Token expires after 30 minutes.

---

## 7. Sensitive Encounter Flag

Sessions marked `is_sensitive = True` (HIV status, mental health, reproductive health,
substance use):

- Audit log records **every view** (not just saves).
- Share / QR transfer is **blocked**.
- AI prompt gains a PHI-minimisation addendum.
- Visible indicator in the session list.

---

## 8. Audit Logging

Two log files rotate at 5 MB (5 backups kept):

| Log | File | Content |
|---|---|---|
| Application | `logs/wellnest.log` | Errors, warnings, pipeline events |
| Audit | `logs/audit.log` | Sensitive access, share blocks, flag changes, intrusion events |

Log format: `[timestamp] LEVEL logger message`

On Azure, logs also stream to App Service stdout and can be forwarded to Azure Monitor /
Log Analytics for centralised SIEM.

---

## 9. Role-Based Access Control

| Role | Can record | Can generate | Can finalize | Can view all | Notes |
|---|---|---|---|---|---|
| Clinician | ✅ | ✅ | ✅ | Own sessions only | Default role |
| Lead | ✅ | ✅ | ✅ | Facility sessions | |
| Admin | ✅ | ✅ | ✅ | Facility + audit logs | |
| Scribe | ✅ | ✅ | ❌ | Own sessions only | Cannot approve notes |
| Nurse | ❌ | ❌ | ❌ | Assigned sessions | View + assist |
| ED Nurse | Limited | ❌ | ❌ | ED board | |
| Receptionist | ❌ | ❌ | ❌ | Session list (no notes) | Read-only |

---

## 10. Audio File Security

Audio files are stored in `media/scribe_audio/YYYY/MM/DD/`.

**Current state:** Files are on the App Service filesystem, protected by:
- Authentication required to access any session (no public URLs for audio).
- Auto-deletion after `AUTO_DELETE_AUDIO_DAYS` (default: 30 days).

**Recommended upgrade:** Move audio to Azure Blob Storage with Customer-Managed Keys
(CMK) for full encryption-at-rest with your own key material.  This is a future
architecture change — see TODO below.

---

## 11. Database Security

| Layer | Control |
|---|---|
| Azure infrastructure | Transparent Data Encryption (TDE) at rest — AES-256, on by default |
| Connection | SSL/TLS enforced (`MYSQL_SSL_CA_PATH` or certifi bundle) |
| Application | Field-level Fernet encryption for all PHI fields (Section 3) |
| Firewall | Azure database firewall — restrict to App Service IP only |
| Credentials | Stored in Azure App Service Application Settings, not in code |

---

## 12. TODO — Security Roadmap

These items are known gaps, prioritised for future implementation:

- [ ] **OAuth 2.0 / SSO** — integrate Azure AD or Google Workspace SSO so facility
      staff can use their existing credentials. Reduces password sprawl and enables
      centrally-managed MFA.
- [ ] **MFA (Multi-Factor Authentication)** — TOTP via `django-two-factor-auth`.
      Compatible with Microsoft Authenticator and Google Authenticator (both free).
      Do NOT use SMS OTP — costs money per message and is less secure than TOTP.
      Enforce for all clinician, lead, and admin roles. High priority — a compromised
      password alone should not be sufficient to access patient data.
- [ ] **Azure Blob Storage + CMK for audio** — move audio files off the App Service
      filesystem to Azure Blob with customer-managed encryption keys.
- [ ] **Key rotation management command** (`manage.py rotate_phi_key`) — re-encrypt all
      PHI rows with a new Fernet key without downtime.
- [ ] **Content Security Policy (CSP)** — add strict CSP header to prevent XSS
      exploitation. Currently blocked by inline scripts in Bootstrap/Iconify.
- [ ] **Rate limiting on API endpoints** — beyond login (django-axes), add per-user
      rate limits on transcript and note generation endpoints.
- [ ] **Database firewall automation** — auto-update Azure firewall rules from CI/CD
      pipeline when App Service outbound IP changes.
- [ ] **Penetration test** — commission a formal pentest before onboarding facilities
      with >50 users or processing data under a formal DPA.

---

## 13. Caribbean Data Protection Compliance Checklist

| Requirement | Status |
|---|---|
| Lawful basis for processing patient data | Consent obtained before recording (timestamp logged) |
| Data minimisation | Patient name/ID optional; pilot mode discourages real names |
| Access control | Role-based, documented above |
| Encryption at rest | Application-layer Fernet + Azure TDE |
| Encryption in transit | TLS enforced, HSTS enabled |
| Audit trail | `audit.log` + `SessionEvent` table |
| Breach notification capability | Intrusion detection emails admin within minutes |
| Data retention limits | Audio auto-deleted (30 days); sessions deletable by clinician |
| Right to erasure | Admin can delete sessions; cascade deletes all linked data |
| Data Processing Agreement (DPA) | TODO — obtain DPA with Microsoft Azure |
| Privacy Policy | Published at `/legal/privacy/` |
| Terms of Service | Published at `/legal/terms/` |
