# WellNest Scribe — Architecture Overview

> **Audience.** Developers and project owners. Not for public distribution — sections marked _internal_ describe model selection and prompt strategy that should not appear in marketing material or be exposed to competitors.

---

## 1. What WellNest Is

A web-based AI medical scribe built specifically for Caribbean (initially Jamaican) healthcare:

- **Voice → SOAP / narrative / chart note** in under a minute.
- Works on phone or laptop. Mobile-first UI with bottom-sheet navigation.
- Specialty-aware (anesthesiology, OB/GYN, paediatrics, neurology, psychiatry, surgery, emergency, general practice…).
- Quick-template scaffolding for the four most common Jamaican health-centre encounters (HTN follow-up, DM follow-up, URTI, gastro, antenatal, paediatric).
- Doctor-controlled inline editing with optional AI grammar polish + missing-detail check.
- QR-code share to move a note from phone to the hospital EHR computer.
- Audit log + retention controls aligned with the **Jamaica Data Protection Act 2020**, with HIPAA / GDPR-leaning defaults.
- Internal **Triage Lab** sandbox (admin-only) for Patois ASR research.

The pilot doctor is Dr Smith, a UWI/MAPEN-affiliated clinician working Mon/Wed/Fri at a Manchester health centre.

---

## 2. High-Level Architecture

```
┌──────────────────────────────┐
│  Doctor's phone or laptop    │   Browser:
│  (Chrome / Edge / Safari)    │   - HTML/CSS/JS only
└──────────┬───────────────────┘   - MediaRecorder API for audio capture
           │ HTTPS                  - Bootstrap 5 (Reback admin theme adapted)
           ▼
┌──────────────────────────────┐
│  Django 5 (Python 3.10)      │   Single process. Stateless except for:
│  - WSGI on a small VPS or    │   - SQLite (dev/pilot) or Postgres (prod)
│    laptop server             │   - media/   (audio uploads)
│  - Reverse proxy (optional)  │   - logs/    (rotating audit + app logs)
└──────────┬───────────────────┘
           │ HTTPS, server-side calls
           ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│  Speech-to-text provider     │    │  Chat-completion provider    │
│  (cloud, swappable)          │    │  (cloud, swappable)          │
└──────────────────────────────┘    └──────────────────────────────┘
                                                       │
                                                       ▼
                          ┌──────────────────────────────────┐
                          │  Optional on-host research path  │  (admin-only Triage)
                          │  Patois ASR (open weights) +     │
                          │  small instruction-tuned model   │
                          └──────────────────────────────────┘
```

**Key design decisions:**

1. **Server-side AI** for the pilot. Audio uploads from the browser; the server calls the cloud transcription + chat APIs. The doctor's device never downloads ML model weights.
2. **Pluggable providers.** The transcription and chat clients are isolated in [`apps/scribe/services/`](apps/scribe/services/). Swap provider by changing one file and the env vars.
3. **Modular prompts.** Generation is one chat call by default (`SCRIBE_PIPELINE_MODE=single`); switchable to per-section modular mode for harder cases.
4. **Refusal-resistant.** Detects when a small reasoning model returns "Not documented" everywhere despite a non-trivial transcript and re-prompts with stricter extraction guidance.
5. **Stub mode.** With `SCRIBE_USE_REAL_AI=False` the entire UI works against deterministic stubs — useful for offline development and demos.

---

## 3. Repository Layout

```
WellnestScribe/
├── admin/                    Original Reback HTML reference (untouched)
├── apps/
│   ├── accounts/             Auth, DoctorProfile, RBAC, email-or-username login
│   │   ├── backends.py       Custom auth backend
│   │   └── management/       promote / demote commands
│   └── scribe/               Sessions, notes, AI services
│       ├── services/
│       │   ├── prompts.py            Prompt library (system + user + section)
│       │   ├── clients.py            Provider client wrappers
│       │   ├── transcription.py      Audio → text
│       │   ├── soap_generator.py     Note generation + polish + interpret
│       │   ├── pipeline.py           Stub-or-real orchestration
│       │   ├── triage.py             Admin sandbox (Patois ASR)
│       │   ├── stub.py               Deterministic offline responses
│       │   └── export.py             QR + share-link helpers
│       └── management/       purge_audio + download_triage_models
├── templates/
│   ├── base.html             Authenticated app shell (sidebar + topbar)
│   ├── base_auth.html        Auth pages (no sidebar)
│   ├── landing.html          Public landing
│   ├── partials/             Topbar, sidebar, mobile bottom-sheet
│   ├── accounts/             Sign-in, sign-up, profile
│   └── scribe/               Record, review, history, triage, audit, compliance
├── static/                   Reback CSS/JS + custom wellnest.css + wellnest.js
├── wellnest/                 Django project (settings, urls, wsgi)
├── media/                    User audio (gitignored)
├── logs/                     Rotating audit + app logs (gitignored)
└── requirements.txt
```

---

## 4. Request Flow — "I just dictated a SOAP note"

```
1. Browser MediaRecorder captures WebM/Opus audio
        │
2. POST /scribe/api/sessions/  (multipart, audio + format + length)
        │   Server creates ScribeSession(status='draft')
3. POST /scribe/api/sessions/<id>/transcribe/
        │   Server reads audio file, calls speech-to-text API
        │   Stores transcript on session
4. POST /scribe/api/sessions/<id>/generate/  (transcript, format)
        │   Server builds system prompt (specialty-aware)
        │   Calls chat completion
        │   Detects refusal/empty patterns and retries if needed
        │   Splits S: O: A: P: into structured fields
        │   Persists SOAPNote
5. Browser redirects to /scribe/sessions/<id>/review/
        │   Doctor edits inline, autosaves every ~1s
        │   Optional: Polish grammar / Check missing details / QR-share
6. POST /scribe/api/sessions/<id>/finalize/  marks reviewed
```

Every step writes to `SessionEvent` (DB) and `logs/audit.log` (rotating file) tagged with `session=<id> doctor=<id> event=<type>`.

---

## 5. Data Model

```
User (Django auth)                 ScribeSession                 SOAPNote
  ├── DoctorProfile                  ├── doctor (FK User)          ├── session (1:1)
  │     ├── role                     ├── audio_file                ├── subjective
  │     ├── specialty                ├── transcript                ├── objective
  │     ├── default_note_style       ├── note_format               ├── assessment
  │     ├── long_form_default        ├── length_mode               ├── plan
  │     ├── theme / font_scale       ├── status                    ├── narrative
  │     └── custom_instructions      ├── error_message             ├── full_note
  └── (auth fields)                  └── timestamps                ├── edited_note
                                                                   ├── flags (json)
                                       SessionEvent                 ├── review_completed
                                         ├── session                └── export_count
                                         ├── event_type
                                         ├── detail                NoteShare
                                         └── created_at              ├── session
                                                                     ├── token (unique)
                                                                     ├── expires_at
                                                                     └── opened_count
```

---

## 6. RBAC

Three roles on `DoctorProfile.role`:

| Role | Sees Triage Lab | Sees /admin/ | Sees Audit log + Compliance |
|---|---|---|---|
| `clinician` (default) | no | no | no |
| `lead` | yes | no | no (unless `is_staff`) |
| `admin` | yes | yes (when also `is_staff`) | yes |

Promotion CLI:

```powershell
python manage.py promote <user> --role admin --staff --superuser
python manage.py demote <user>
```

**First-run bootstrap:** if zero admins exist, the Profile page surfaces a one-shot "Make me the first admin" button. Disappears as soon as any admin is set.

---

## 7. AI Layer (_internal_)

This section describes how the AI side is structured. **Do not publish externally.** The specific model names, prompts, and refusal-recovery logic are dev-only signal.

### 7.1 Provider abstraction

`apps/scribe/services/clients.py` wraps two clients:

- A speech-to-text client (cloud).
- A chat-completion client (cloud, distinct provider).

Both are constructed lazily and cached. Swapping providers means editing this file + the matching env vars; the rest of the code uses the abstraction.

### 7.2 Prompt layers

`apps/scribe/services/prompts.py` is the source of truth.

```
Layer 1: MASTER_SYSTEM_PROMPT     — universal rules (extraction-first, plain text, no invention)
Layer 2: JAMAICAN_CONTEXT_ADDENDUM — herbs, Patois phrases, common meds
Layer 3: specialty addendum        — anesthesia / OB-GYN / paediatrics / etc.
Layer 4: doctor's custom_instructions
Layer 5: User prompt               — SOAP / narrative / chart variant + transcript
```

The user prompt embeds a worked example so small reasoning models don't default to refusal.

### 7.3 Refusal-resistant generation

When ≥ 3 of the 4 SOAP sections come back as "Not documented" but the transcript exceeds 60 chars:

1. Send the previous (over-conservative) attempt back as an `assistant` message.
2. Append a `user` follow-up that explicitly asks the model to extract the clinical content.

Catches the failure mode where small reasoning models burn the entire token budget on internal reasoning + then write nothing.

### 7.4 Polish + Improve + Patois interpret

Three optional cloud calls, all manual (never auto-fired to control cost):

- **`polish_grammar`** — preserves every clinical fact, fixes phrasing/spelling/abbreviations.
- **`suggest_improvements`** — returns 3-6 bullet suggestions; never invents diagnoses.
- **`interpret_patois`** — reads raw Patois ASR output and outputs clean clinical English. Used by the Triage sandbox, not the primary pipeline.

### 7.5 Triage Lab (admin-only)

Internal research surface to test on-device Patois ASR (open-weights speech model + small instruction-tuned model) plus a cloud-interpret fallback. CPU/GPU toggle, audio capture and replay, custom system prompt textarea. Hidden from regular pilot doctors entirely.

---

## 8. Compliance Posture

| Control | Implementation |
|---|---|
| Cookies | `Secure` (when DEBUG off), `HttpOnly`, `SameSite=Lax` |
| Session lifetime | 8h absolute, rolling on activity, idle warning + auto-signout at 15 min |
| Headers | `X-Frame-Options: DENY`, no-sniff, strict-origin referrer |
| Transport | HSTS 1 year + SSL redirect when `DEBUG=False` |
| Auth | Email-or-username login, role-based access, audit log per actor |
| Audit | Every session create / edit / generate / export / finalize → DB + rotating log file |
| Retention | Audio auto-purge after `AUTO_DELETE_AUDIO_DAYS` (default 30) via `purge_audio` command |
| PHI | No patient names required; encounter IDs only during pilot |
| Disclaimer | Every note ends with "AI-generated draft — review and edit required before clinical use." |

---

## 9. Deployment Options

### 9.1 Single-server pilot (recommended for now)
- DigitalOcean droplet / Azure App Service / Render
- Gunicorn + Nginx, Postgres, S3-compatible storage for audio
- Doctors connect from any device; nothing to install
- ~$15-30/month

### 9.2 Docker (recommended once you scale beyond Dr Smith)
- One image, all deps + cached models (optional)
- Volume mounts for `media/` and the SQLite/Postgres DB
- Distribute to multiple clinics with `docker run` instead of bespoke installs

### 9.3 Windows packaged install (for low-internet clinics)
- Bundle Python + Django + cached models with PyInstaller or pywebview
- App runs on the doctor's laptop, serves HTTP on `localhost:8765`, opens default browser
- Sync notes to cloud when internet returns
- Heavier to ship + maintain than web; only worth it if connectivity really is the blocker

### 9.4 Desktop wrapper
- Tauri (Rust shell + your existing web UI)
- pywebview (Python shell, much smaller dep)
- Either gives a "looks like an app" install without rewriting Django

### 9.5 Browser-side (offline) — research path
- ONNX runtime / WebAssembly transformers.js for the speech model
- Tiny LLM (Gemma 1B / Llama-3.2 1B quantized) via WebGPU
- Doctor downloads model once; cached in IndexedDB; works offline thereafter
- Higher latency, lower accuracy than cloud — prototype on the Triage Lab first

---

## 10. Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Optional Triage stack (admin-only, ~5 GB):

```powershell
pip install transformers accelerate librosa soundfile sentencepiece
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
python manage.py download_triage_models
```

Switch between providers / pipelines via `.env`:

```env
SCRIBE_USE_REAL_AI=True
SCRIBE_PIPELINE_MODE=single        # or 'modular'
SCRIBE_MAX_COMPLETION_TOKENS=4000  # bump for reasoning models
```

---

## 11. Roadmap

Short-term (weeks):
- [ ] Background job queue (Celery or Django-Q) so transcription/generation don't block the request thread on slow days.
- [ ] Multi-doctor pilot at one health centre (Dr Smith + 2-3 colleagues).
- [ ] Real-world Patois audio dataset collection for Triage fine-tuning.

Medium (months):
- [ ] Browser extension to auto-fill the EHR note field (replaces copy-paste).
- [ ] Edge-mode (offline) doctor laptop bundle with on-device speech + small LLM.
- [ ] Drug-interaction checker (Feature #2 on the BMC).

Long (year):
- [ ] FHIR DocumentReference push to hospital EHRs that support it.
- [ ] Ambient-listening mode with speaker diarization (vs. dictation-after-encounter).
- [ ] Patois-tuned ASR adapter shipped as the Caribbean moat.

---

*Last updated: 2026-05-05.*
