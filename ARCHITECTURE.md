# WellNest Scribe — Architecture Overview

> **Audience.** Developers and project owners. Not for public distribution — sections marked _internal_ describe model selection and prompt strategy that should not appear in marketing material or be exposed to competitors.

---

## 0. Current Stack Summary (2026-07) — read this first

This is exactly what is running **right now**. (Later sections retain more detail; where they disagree with this table, this table wins — the older sections predate the Render→Azure and MMS→omniASR moves.)

| Layer | Technology (current) |
|---|---|
| Web framework | **Django 5.0.6** (Python), server-rendered templates + vanilla JS (no SPA framework) |
| Hosting | **Microsoft Azure App Service (Linux, B1: 1 vCPU / 1.75 GB)**, Gunicorn **`gthread`** workers |
| Database | **Aiven MySQL** (managed cloud, TLS), `CONN_MAX_AGE=60`. SQLite for local dev. |
| Static / PWA | WhiteNoise; service-worker PWA shell |
| **Transcription (ASR)** | **omniASR (CTC variant) on Modal — T4 GPU.** Endpoints registered in the `ModalOmniEndpoint` DB table, selected by profile (`low`/`mid`/`high`) with health-checked failover. **Measured ~$0.05/audio-hour.** (`AMBIENT_BACKEND=modal-omni`.) Legacy `gpt-4o-transcribe` and Modal-MMS paths remain in code as fallbacks. |
| **Note generation** | **Azure OpenAI `gpt-5-chat`** deployment (product-branded "Cadence"). **$2.50 in / $15 out per 1M tokens** (measured & confirmed). **Single combined interpret+generate call** (`SCRIBE_COMBINED_PIPELINE=True`), `reasoning_effort=minimal`. **Measured ~$0.045–0.05/note.** |
| Language routing (v3) | `jam_Latn` → Patois interpreter → Jamaica-context SOAP · low-resource (`hat`/`wol`/`kin`) → generalized interpreter · all high-resource → skip interpreter |
| Cost telemetry | Every GPT call logged to **`ModelUsageLog`** (prompt/completion/reasoning tokens + computed $); report via `python manage.py ai_cost_report`. omniASR cost derived from session audio duration. |
| Apps | `accounts` (auth, RBAC, **10 roles**), `scribe` (AI notes — core), `emr` (org-scoped records), `ed` (emergency dept) |
| Security | PHI fields **encrypted at rest** (`EncryptedTextField`); **django-axes** brute-force lockout; client-side **idle auto-lock**; **4h** session cap; **Intrusion-Detection dashboard** (`SecurityEvent`); encrypted QR phone→desktop handoff |
| Usage / billing | **Note-credit model** (1 credit per note ≤20 min, **+1 per extra 20 min**); per-doctor monthly meter in the topbar; per-note AI-op caps (regenerate/polish/magic-edit); 3-hour recording auto-stop |
| Observability | Admin **Server Monitor** page (live CPU/mem/workers/DB), **Intrusion Detection** page, token/cost logging |
| Middleware | `DemoLockdownMiddleware` (kill-switch), `SecurityAuditMiddleware` (IDS), `UsageContextMiddleware` (tags GPT calls for cost) |

**Real-time UI:** short polling (worklist + queue every ~5–12 s, self-throttling) — **no Redis, no websockets**; the always-on SSE was scoped to `/scribe/` only. See §14.

---

## 1. What WellNest Is

A web-based AI medical scribe built specifically for Caribbean (initially Jamaican) healthcare:

- **Voice → SOAP / narrative / chart note** in under a minute via dictation or ambient room recording.
- Works on phone or laptop. Mobile-first UI with bottom-sheet navigation.
- Specialty-aware (anesthesiology, OB/GYN, paediatrics, neurology, psychiatry, surgery, emergency, general practice…).
- Quick-template scaffolding for common Jamaican health-centre encounters (HTN follow-up, DM follow-up, URTI, gastro, antenatal, paediatric).
- Doctor-controlled inline editing with AI grammar polish + missing-detail check.
- QR-code share to move a note from phone to the hospital EHR computer.
- **Emergency Department module** — tracking board, ESI triage, zone management, shift handover.
- **EMR module** — organisation-scoped patient records, encounters, medications, referrals, appointments.
- Audit log + retention controls aligned with the **Jamaica Data Protection Act 2020**, with HIPAA/GDPR-leaning defaults.
- Internal **Triage Lab** sandbox (staff-only) for Patois ASR research.

The pilot doctor is Dr Smith, a UWI/MAPEN-affiliated clinician working at a Manchester health centre.

---

## 2. High-Level Architecture

```
┌──────────────────────────────┐
│  Doctor's phone or laptop    │   Browser:
│  (Chrome / Edge / Safari)    │   - HTML/CSS/vanilla JS (no framework)
└──────────┬───────────────────┘   - MediaRecorder API for audio capture
           │ HTTPS                  - Bootstrap 5 (Reback admin theme adapted)
           ▼
┌──────────────────────────────┐   Gunicorn gthread workers. State:
│  Django 5 (Python)           │   - Aiven MySQL (cloud, production, TLS)
│  Azure App Service (Linux B1)│   - SQLite (dev)
│  1 vCPU / 1.75 GB            │   - media/  (audio, auto-purged)
│                              │   - logs/   (rotating audit + app logs)
└──────────┬───────────────────┘
           │ HTTPS, server-side calls
           ├──────────────────────────────────────────┐
           ▼                                          ▼
┌──────────────────────────────────┐   ┌────────────────────────────────┐
│  Modal — T4 GPU (cloud)          │   │  Azure OpenAI                  │
│  omniASR (CTC) speech → text     │   │  gpt-5-chat = "Cadence"        │
│  ModalOmniEndpoint registry      │   │  interpret+generate (1 call),  │
│  profiles: low / mid / high      │   │  polish, magic-edit, drug check│
│  ~$0.05 / audio-hour (measured)  │   │  $2.50/$15 per 1M tok          │
└──────────────────────────────────┘   └────────────────────────────────┘
           │  (fallbacks still in code: gpt-4o-transcribe · Modal-MMS · on-device CPU MMS)
```

**Key design decisions:**

1. **Server-side AI.** Audio uploads from the browser; the server calls cloud transcription + chat APIs. The doctor's device never downloads ML model weights.
2. **Pluggable providers.** Transcription and chat clients are isolated in `apps/scribe/services/`. Swap provider by changing one file and the env vars.
3. **Modular prompts.** Generation is one chat call by default (`SCRIBE_PIPELINE_MODE=single`); switchable to per-section modular mode.
4. **Refusal-resistant.** Detects when a reasoning model returns "Not documented" across ≥3 SOAP sections despite a non-trivial transcript and re-prompts with stricter extraction guidance.
5. **Async jobs for heavy work.** Patois ASR (MMS) and model downloads use an in-memory thread-pool job registry (`triage_jobs.py`) — the API returns a `job_id` immediately; the client polls for completion. No external queue needed for the single-server pilot.
6. **Stub mode.** With `SCRIBE_USE_REAL_AI=False` the entire UI works against deterministic stubs — useful for offline development and demos.

---

## 3. Repository Layout

```
WellnestScribe/
├── apps/
│   ├── accounts/             Auth, DoctorProfile, RBAC, 7-role system
│   │   ├── backends.py       Email-or-username auth backend
│   │   ├── templatetags/     Custom template filters
│   │   └── management/       promote / demote CLI commands
│   ├── scribe/               Sessions, notes, AI services (core feature)
│   │   ├── services/
│   │   │   ├── clients.py            Provider client wrappers (lazy, cached)
│   │   │   ├── transcription.py      Audio → text (gpt-4o-transcribe)
│   │   │   ├── soap_generator.py     Note generation, polish, interpret, magic edit
│   │   │   ├── prompts.py            Prompt library (system + user + section templates)
│   │   │   ├── pipeline.py           Stub-or-real orchestration
│   │   │   ├── triage.py             Patois ASR sandbox + Modal MMS client
│   │   │   ├── triage_jobs.py        In-memory async job registry
│   │   │   ├── drug_check.py         Drug interaction checker
│   │   │   ├── stub.py               Deterministic offline responses
│   │   │   └── export.py             QR + share-link helpers
│   │   └── management/       purge_audio + download_triage_models
│   ├── ed/                   Emergency Department module
│   │   ├── services/
│   │   │   ├── ai_esi.py     AI-assisted ESI triage scoring
│   │   │   └── handover.py   AI SBAR shift-handover generation
│   │   └── management/
│   └── emr/                  Organisation-scoped EMR
│       ├── services/
│       │   ├── access.py     Organisation-scoped access control
│       │   ├── audit.py      EMR audit logging
│       │   ├── scribe_import.py  Link scribe session → EMR encounter
│       │   └── search.py     Patient search across organisation
│       └── backends/
│           ├── base.py           Abstract backend interface
│           ├── local_backend.py  Django ORM (default)
│           ├── gnuhealth_backend.py  GNU Health Tryton integration
│           └── registry.py       Backend selection (EMR_BACKEND setting)
├── templates/
│   ├── base.html             Authenticated app shell
│   ├── base_auth.html        Auth pages (no sidebar)
│   ├── landing.html          Public landing
│   ├── partials/             Topbar, sidebar, nav items, mobile bottom-sheet
│   ├── accounts/             Sign-in, sign-up, profile, users_admin
│   ├── scribe/               Record, review, history, triage, drug-check, audit, compliance
│   └── ed/                   Tracking board, triage form, visit detail, shift handover
├── static/                   Reback CSS/JS + custom wellnest.css + wellnest.js
├── wellnest/                 Django project (settings, urls, wsgi, pwa)
├── media/                    User audio + images (gitignored)
├── logs/                     Rotating audit + app logs (gitignored)
├── certs/                    SSL/TLS certs for DB connections
└── requirements.txt
```

---

## 4. Request Flows

### 4.1 Dictation mode — "I just recorded and dictated a SOAP note"

```
1. Browser MediaRecorder captures WebM/Opus audio
        │
2. POST /scribe/api/sessions/  (multipart — audio + format + length + patient fields)
        │   Server creates ScribeSession(status='draft', session_type='dictation')
3. POST /scribe/api/sessions/<id>/transcribe/
        │   Server reads audio file → gpt-4o-transcribe
        │   Stores transcript on session
4. POST /scribe/api/sessions/<id>/generate/  (transcript, format, specialty)
        │   Server builds layered system prompt
        │   Calls Azure chat completion
        │   Detects refusal/empty patterns and retries if needed
        │   Splits S/O/A/P into structured fields → persists SOAPNote
5. Browser redirects to /scribe/sessions/<id>/review/
        │   Doctor edits inline, autosaves
        │   Optional: Polish / Check missing details / Magic edit / QR-share
6. POST /scribe/api/sessions/<id>/finalize/  marks reviewed
```

### 4.2 Ambient mode — "I recorded the whole consultation in the room"

```
1. Browser MediaRecorder captures WebM/Opus audio (ambient recording tab)
        │
2. POST /scribe/api/sessions/  (multipart — audio blob, note_format, patient fields)
        │   Server creates ScribeSession(status='draft', session_type='ambient')
        │   Audio file saved to disk
3. POST /scribe/api/sessions/<id>/ambient-transcribe/  {backend: "modal"|"local"}
        │   Returns {ok, job_id} immediately
        │   Spawns daemon thread (triage_jobs.py)
        │     modal path: ffmpeg converts webm→WAV, POST to Modal L4 GPU
        │                 → facebook/mms-1b-l1107 (target_lang=jam)
        │     local path: Load MMS model on CPU (60–120 s first run)
4. Client polls GET /scribe/api/ambient-jobs/<job_id>/  every 2 s
        │   Returns {status, stage, elapsed_ms, result}
        │   status: pending → running → done | error
5. On done: POST /scribe/api/sessions/<id>/generate/  (raw transcript)
        │   Same SOAP generation flow as dictation
6. Browser redirects to review
```

Every step writes to `SessionEvent` (DB) and `logs/audit.log` tagged with `session=<id> doctor=<id> event=<type>`.

---

## 5. Data Model

### 5.1 Scribe app

```
ScribeSession
  ├── doctor (FK User)
  ├── audio_file, duration_seconds
  ├── raw_transcript          ← original ASR output, never overwritten
  ├── transcript              ← clean/processed text used for generation
  ├── note_format (soap|narrative|chart)
  ├── length_mode (concise|normal|long_form)
  ├── session_type (dictation|ambient|text)
  ├── status (draft→recording→transcribing→generating→review→finalized|error)
  ├── is_sensitive            ← blocks share links, PHI-minimises prompt
  ├── consent_acknowledged_at
  ├── patient_name, patient_identifier, patient_gender
  ├── active_conditions       ← comma-separated shorthand (dm, htn, …)
  └── timestamps (created_at, updated_at, finalized_at)

SOAPNote  (1:1 ScribeSession)
  ├── visit_summary, subjective, objective, assessment, plan
  ├── narrative, full_note, edited_note
  ├── body_markers (JSON)     ← wound/injury annotations with coords + 15+ clinical fields
  ├── wound_chart (JSON)      ← NATVNS patient-level wound record
  ├── flags (JSON), review_completed, export_count

NoteShare
  ├── session (FK), token (unique), expires_at, opened_count

DrugAlias
  ├── brand_name, generic_name, drug_class
  ├── jamaican_common (bool), notes

DrugInteractionCheck
  ├── doctor (FK), inputs (JSON), result (JSON)
  ├── duration_ms, model_used

SessionEvent
  ├── session (FK), event_type, detail, created_at
```

### 5.2 Accounts app

```
DoctorProfile  (1:1 User)
  ├── role: clinician|lead|admin|scribe|ed_nurse|nurse|receptionist
  ├── specialty: general|internal|anesthesia|surgery|obgyn|
  │              pediatrics|psychiatry|neurology|cardiology|emergency|family|other
  ├── custom_instructions, custom_terms (abbrevs + definitions)
  ├── custom_drugs (JSON)     ← doctor-specific medication picker entries
  ├── default_note_style, long_form_default, suggestive_assist
  ├── theme (light|dark|auto), font_scale
  └── facility, full_name, title
```

### 5.3 ED app (summary)

```
EDVisit → TriageAssessment (1:1), DispositionRecord (1:1)
        → ZoneAssignment (1:many)
        → emr.Encounter (1:1, optional)

EDShift → ShiftHandoverNote (1:many, one per visit per shift)
```

Key EDVisit fields: 5 mandatory timestamps (arrived → triaged → seen_by_doctor → disposition_decided → exited), ESI score (AI-assisted), zone/bed tracking, 8 visit statuses.

Key TriageAssessment fields: 9 vitals, GCS (eye/verbal/motor), ESI score + AI suggestion + override reason, 9 PMH flags, allergies, pregnancy status.

### 5.4 EMR app (summary)

```
Organisation → OrganisationMembership (many:many User)
            → Patient (1:many)
                └── Allergy, Appointment, Encounter, Vital,
                    Diagnosis, Medication, Referral, Immunisation
```

Patient has full Jamaican identity fields: NHF card, TRN, NIDS number, parish, NHF programme, private insurer, blood group, herbal history, consent fields.

---

## 6. RBAC

Seven roles on `DoctorProfile.role`:

| Role | Scribe | ED board | Triage Lab | Admin panel | Audit/Compliance |
|---|---|---|---|---|---|
| `clinician` (default) | yes | no | no | no | no |
| `scribe` | yes | no | no | no | no |
| `nurse` | yes | limited | no | no | no |
| `ed_nurse` | no | yes (triage) | no | no | no |
| `lead` | yes | yes | yes | no | no |
| `admin` | yes | yes | yes | yes (if `is_staff`) | yes |
| `receptionist` | limited | limited | no | no | no |

Access gating is via `DoctorProfile` methods: `can_access_triage()`, `can_use_scribe()`, `can_use_ed_board()`, `can_finalize()`, `is_read_only()`.

Promotion CLI:

```powershell
python manage.py promote <user> --role admin --staff --superuser
python manage.py demote <user>
```

**First-run bootstrap:** if zero admins exist, the Profile page surfaces a one-shot "Make me the first admin" button that disappears once any admin is set.

---

## 7. AI Layer (_internal_)

### 7.1 Provider abstraction

`apps/scribe/services/clients.py` wraps two lazily-initialised, cached clients:

- **Transcription client** — OpenAI (default) or Azure OpenAI, targeting `gpt-4o-transcribe` family.
- **Chat client** — Azure OpenAI, targeting `gpt-5-chat` deployment.

Swapping providers = edit this file + change env vars. All other code uses the abstraction.

### 7.2 Prompt layers

`apps/scribe/services/prompts.py` is the source of truth.

```
Layer 1: MASTER_SYSTEM_PROMPT     — universal rules (extraction-first, plain text, no invention)
Layer 2: JAMAICAN_CONTEXT_ADDENDUM — herbs, Patois phrases, common Caribbean meds
Layer 3: specialty addendum        — anesthesia / OB-GYN / paediatrics / ED / etc.
Layer 4: doctor's custom_instructions + custom_terms
Layer 5: User prompt               — SOAP / narrative / chart variant + transcript
```

The user prompt embeds a worked example so small reasoning models don't default to refusal.

### 7.3 Refusal-resistant generation

When ≥ 3 of the 4 SOAP sections come back as "Not documented" but the transcript exceeds 60 chars:

1. Send the previous (over-conservative) attempt back as an `assistant` message.
2. Append a `user` follow-up that explicitly asks the model to extract the clinical content.

Catches the failure mode where reasoning models burn the entire token budget on internal reasoning then write nothing.

### 7.4 Post-generation tools

Three optional cloud calls, all manual (never auto-fired to control cost):

- **`polish_grammar`** — preserves every clinical fact, fixes phrasing/spelling/abbreviations.
- **`suggest_improvements`** — returns 3–6 bullet suggestions; never invents diagnoses.
- **`interpret_patois`** — reads raw Patois ASR output and returns clean clinical English. Used by the Triage sandbox.
- **`magic_edit_note`** — freeform edit instruction applied to the current draft.

### 7.5 Drug interaction checker

`apps/scribe/services/drug_check.py`:

1. Resolve input names through `DrugAlias` (brand → generic, Jamaican synonyms).
2. Build a structured prompt with the DRUG_INTERACTION_PROMPT template.
3. Call Azure chat (gpt-5-chat).
4. Parse JSON response → severity flags, explanation, alternatives.
5. Log to `DrugInteractionCheck` table (doctor + inputs + result + timing).

### 7.6 Ambient / Patois ASR

> **Current default (2026-07):** **omniASR (CTC) on Modal T4** via `transcribe_modal_omni()` and the `ModalOmniEndpoint` registry (profiles low/mid/high, priority order + health-check failover, `X-API-Key` auth). `AMBIENT_BACKEND=modal-omni`. ~$0.05/audio-hour measured. The MMS paths below are retained as fallbacks.

`apps/scribe/services/triage.py`:

- **`transcribe_modal_omni()`** — POST audio (webm→WAV via ffmpeg) to the active `ModalOmniEndpoint` (`/transcribe/omni/file`). **Primary path.**
- **`transcribe_modal_mms()`** _(fallback)_ — POST webm to a Modal MMS endpoint. Authenticates with `X-API-Key`. Returns timing stats.
- **`transcribe_mms()`** — Local CPU path: loads `facebook/mms-1b-l1107` on demand, resamples audio to 16 kHz mono, chunks at 25 s, aggregates transcript.
- Both paths go through the `triage_jobs.py` async thread pool — the request returns a `job_id` in < 100 ms; the client polls.

### 7.7 ED AI features

- **ESI scoring** (`apps/ed/services/ai_esi.py`) — given vitals + chief complaint, suggests ESI 1–5 with rationale. Physician can override.
- **SBAR handover** (`apps/ed/services/handover.py`) — generates situation/background/assessment/recommendation summary for shift handover.
- **Voice-to-vitals** — ED triage form accepts dictated vitals; parsed via structured chat call.

### 7.8 Triage Lab (staff-only)

Internal research surface to test on-device Patois ASR. CPU/GPU toggle, audio capture and replay, custom system prompt textarea, latency stats display. Hidden from regular pilot doctors entirely.

---

## 8. Async Job Architecture

`apps/scribe/services/triage_jobs.py` — in-memory thread-pool registry.

```python
TriageJob:
  job_id: str          # urlsafe token
  status: str          # pending | running | done | error | cancelled
  stage: str           # human-readable progress hint
  result: dict         # raw_text, session_id, timing stats, …
  error: str           # exception message on failure
  elapsed_ms: int      # computed from timestamps
```

- `submit(backend, device, target_fn)` → spawns daemon thread, returns job immediately
- `get(job_id)` → thread-safe dict lookup
- `reap_old(max_age=3600)` → bound memory by clearing old completed jobs

**Limitation:** single-process only. In a multi-worker Gunicorn deploy, jobs and ownership maps are not shared across workers. Adequate for the pilot; scale to Celery + Redis for multi-worker.

---

## 9. EMR Backend Abstraction

`apps/emr/backends/` provides a swappable backend:

| Setting | Backend | Notes |
|---|---|---|
| `EMR_BACKEND=local` | `LocalBackend` (default) | Django ORM, same DB as main app |
| `EMR_BACKEND=gnuhealth` | `GNUHealthBackend` | Calls GNU Health Tryton JSON-RPC; requires Docker stack (`gnuhealth/`) |

Backend selection in `registry.py`. All EMR views call `get_backend()` rather than ORM directly.

---

## 10. Compliance Posture

| Control | Implementation |
|---|---|
| Cookies | `Secure` (DEBUG off), `HttpOnly`, `SameSite=Lax` |
| Session lifetime | **4 h absolute** (reduced from 8 h for PHI); `SESSION_SAVE_EVERY_REQUEST=False`; client-side idle auto-lock (re-auth) + auto-signout |
| PHI at rest | Encrypted via `EncryptedTextField` (transcripts, patient identity, notes) |
| Brute force | `django-axes` lockout on repeated failed logins; failed logins also feed the IDS (`SecurityEvent`) |
| Headers | `X-Frame-Options: DENY`, no-sniff, strict-origin referrer |
| Transport | HSTS 1 year + SSL redirect when `DEBUG=False` |
| Auth | Email-or-username login, 7-role RBAC, per-actor audit log |
| Audit | Session create / transcribe / generate / edit / export / finalize / delete → DB + rotating log |
| Retention | Audio auto-purge after `AUTO_DELETE_AUDIO_DAYS` (default 30) via `purge_audio` command |
| PHI | No patient names required; encounter IDs only during pilot. `is_sensitive` flag enhances logging and PHI-minimises prompts. |
| Consent | `consent_acknowledged_at` timestamp recorded when doctor taps consent gate |
| Disclaimer | Every note ends with "AI-generated draft — review and edit before clinical use." |
| Erasure | `POST /api/sessions/<pk>/delete/` hard-deletes audio + note; logged to audit trail |

---

## 11. Deployment

### 11.1 Current (Microsoft Azure App Service)

- **Platform:** **Azure App Service (Linux), B1 SKU** — 1 vCPU / 1.75 GB. (Was Render; migrated.)
- **Process:** **Gunicorn `gthread`** — the Startup Command / Procfile must set `--worker-class gthread --workers 2-3 --threads 4 --timeout 300`. A default single **sync** worker serialises the whole site and causes site-wide freezes/504s under concurrency — this was the root cause of the worklist-freeze incident; gthread is required.
- **Also set:** `DEBUG=False`, **Always On = On** (stops idle spin-down / cold-start on the first request after quiet periods).
- **DB:** MySQL on **Aiven** cloud (TLS via `certs/`), `CONN_MAX_AGE=60`. **Cross-region latency (~125 ms/query) is the #1 remaining perf factor — co-locate the DB in the app's Azure region.**
- **Static files:** WhiteNoise middleware.
- **Media:** `media/` on the instance (ephemeral — audio auto-purged after `AUTO_DELETE_AUDIO_DAYS`; move to Azure Blob for persistence at scale).
- **Scaling path:** scale up (P-series, multi-core) + scale out (N instances, autoscale on CPU) once past a few dozen concurrent users; see `docs/roadmap/scaling_architecture.md`.

Required env vars for production:

```env
SECRET_KEY
DEBUG=False
ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS
AZURE_MYSQL_HOST / NAME / USER / PASSWORD / PORT
MYSQL_SSL_CA=certs/aiven_ca.pem
WEBSITE_HOSTNAME
SCRIBE_USE_REAL_AI=True
SCRIBE_OPENAI_API_KEY
SCRIBE_OPENAI_TRANSCRIBE_MODEL
SCRIBE_AZURE_OPENAI_ENDPOINT / KEY / DEPLOYMENT_NAME
MODAL_MMS_URL, MODAL_MMS_API_KEY   # ambient mode
AMBIENT_BACKEND=modal
TIME_ZONE=America/Jamaica
```

### 11.2 Docker (when scaling beyond Dr Smith)

```yaml
# Single image, all deps
# Volume mounts for media/ + DB
docker run -p 8000:8000 --env-file .env wellnest
```

GNU Health EMR backend requires a separate `gnuhealth/` Docker Compose stack.

### 11.3 Windows packaged install (low-internet clinics)

- Bundle Python + Django + cached models with PyInstaller or pywebview.
- App runs on the doctor's laptop, serves HTTP on `localhost:8765`, opens default browser.
- Sync notes to cloud when internet returns.
- Heavier to maintain; only worth it if connectivity is genuinely the blocker.

---

## 12. Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Key `.env` switches for development:

```env
SCRIBE_USE_REAL_AI=False          # use deterministic stubs
DJANGO_USE_SQLITE=true            # skip MySQL
SCRIBE_PIPELINE_MODE=single       # or 'modular'
SCRIBE_ENABLE_TRIAGE=True         # show Triage Lab (requires is_staff)
AMBIENT_BACKEND=modal             # or 'local'
```

Optional Triage stack (staff-only, ~5 GB):

```powershell
pip install transformers accelerate librosa soundfile sentencepiece
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
python manage.py download_triage_models
```

For the Modal ambient backend, `ffmpeg` must be in PATH to convert browser WebM files before upload (Modal's MMS validation requires proper audio duration metadata). Install via [ffmpeg.org](https://ffmpeg.org/download.html) or `choco install ffmpeg` on Windows.

---

## 13. Roadmap

**Completed since last architecture snapshot:**
- [x] Async job queue for MMS transcription (in-memory thread pool)
- [x] Ambient listening mode with Modal GPU + local CPU fallback
- [x] Drug interaction checker (feature #2 on the BMC)
- [x] Patient identity system (disambiguation, history, session resume)
- [x] ED module (tracking board, ESI triage, shifts, dispositions)
- [x] EMR module (patient records, encounters, EMR backend abstraction)
- [x] DPA compliance (consent gate, session erasure, breach docs)

**Short-term (weeks):**
- [ ] Multi-doctor pilot at one health centre (Dr Smith + 2–3 colleagues).
- [ ] Real-world Patois audio dataset collection for Triage fine-tuning.
- [ ] S3/object storage for audio (Render's filesystem is ephemeral).
- [ ] Celery + Redis job queue to replace in-memory thread pool (needed for multi-worker).

**Medium (months):**
- [ ] Browser extension to auto-fill the EHR note field (replaces copy-paste).
- [ ] Speaker diarization in ambient mode (doctor vs. patient voice separation).
- [ ] Edge-mode (offline) doctor laptop bundle with on-device speech + small LLM.

**Long (year):**
- [ ] FHIR DocumentReference push to hospital EHRs that support it.
- [ ] Patois-tuned MMS adapter fine-tuned on collected Jamaican clinical audio.

---

## 14. What's New (2026-07) — recent subsystems

Added since the older sections above; these reflect the current system.

**Cost & usage metering (task "T5").**
- **`ModelUsageLog`** — every GPT call (via the central `_chat` chokepoint) logs prompt/completion/reasoning tokens + computed cost. `UsageContextMiddleware` tags each call with session/doctor/type. Report: `python manage.py ai_cost_report --hours N`. omniASR cost is derived from `ScribeSession` audio duration.
- **Note-credit model** — usage is metered in credits: 1 per note ≤ 20 min, **+1 per additional 20 min** (a 1-hour note = 3, a 4-hour = 12). Closes the "one long recording = one note" loophole. Standard 500 credits/mo, Professional 1,100. Per-doctor monthly meter is a topbar pill + popover (`/scribe/api/usage/`).
- **Per-note AI-op caps** — regenerate 12, grammar-polish 6, magic-edit 8 (fields on `ScribeSession`).
- **Recording safeguards** — hard **auto-stop at 3 h** (saves the note) + on-screen nudge at 90 min.

**Security & Intrusion Detection.**
- **`SecurityEvent`** model + `SecurityAuditMiddleware` persist rapid-access, impossible-travel, endpoint-probing, and failed-login (via `user_login_failed` signal) events. Admin **Intrusion Detection** dashboard at `/accounts/security/`.
- **PHI encrypted at rest** (`EncryptedTextField` on transcripts, patient identity, etc.), **django-axes** brute-force lockout, client-side **idle auto-lock**, session cut to **4 h**. **Triage Lab is now admin-only.**

**Observability.** Admin **Server Monitor** at `/scribe/ops/server/` — live CPU %, memory %, **gunicorn worker count**, and a DB round-trip ping, on canvas charts (reads Linux `/proc`).

**Performance / real-time — deliberately no Redis, no websockets.** Short polling for the worklist and queue (self-throttling with exponential backoff, signature-diff so the DOM only swaps on real change, pauses when the tab is hidden). The always-on QR-handoff SSE was scoped to `/scribe/` only; `SESSION_SAVE_EVERY_REQUEST=False`; `PlatformControl` cached; N+1 queries batched; `gthread` workers. Rationale + scale plan in `docs/roadmap/scaling_architecture.md`.

**Next cost lever — prompt caching.** Measured: the ~8K-token static system prompt is ~90% of GPT cost and `reasoning_tokens ≈ 0`. Restructuring prompts so the static block is a stable **cache prefix** roughly halves input cost — a codebase change only (Azure caching is automatic, no portal setting).

**Middleware order:** `DemoLockdownMiddleware` → `SecurityAuditMiddleware` → `UsageContextMiddleware`.

**Roles:** now **10** on `DoctorProfile.role` (added `radiologist`, `pharmacist`, `lab_tech` to the seven in §6).

---

*Last updated: 2026-07-12. Sections 0, 2, 11 and 14 are current; earlier sections retain design detail but predate the Render→Azure and MMS→omniASR migrations.*
