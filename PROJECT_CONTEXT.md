# WellNest Scribe — Master Context Document

**Audience.** Coding agents (you) and developers who need full context before touching the repo. **Read this first.** Sections marked _internal_ are dev-only and should not appear in marketing.

**Project owners.** Adrian (AI/ML lead) + Gary (CS). Pilot clinicians: Dr Smith (UWI/MAPEN, GP, Jamaica) and Dr Elizabeth (GP, Barbados).

**Project goal.** Caribbean-native AI medical scribe. Voice → SOAP / narrative / chart note in under a minute. Built for Jamaican clinical workflow, code-switched English/Patois, and low-bandwidth conditions.

---

## 0. Quickstart for a brand-new coding agent

```powershell
cd c:\xampp\htdocs\WellnestScribe
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py runserver
```

Always activate the venv before running anything. `DJANGO_SETTINGS_MODULE=wellnest.settings` lives in `.env`.

Before you change anything: read **section 10 (conventions)** and **section 14 (gotchas)** — they encode bugs we already paid for.

---

## 1. Tech stack at a glance

| Layer | Choice | Why |
|---|---|---|
| Web framework | Django 5 (Python 3.10) | Owners know Django; batteries included |
| DB | MySQL (prod) / SQLite (dev fallback via `DATABASE_URL`) | Friend switched to MySQL after pilot setup |
| Frontend | Bootstrap 5 + Reback admin theme adapted | No JS framework — keeps deps lean and mobile-friendly |
| PWA | manifest + service worker | Doctors can "install" to phone home screen |
| Audio capture | Browser `MediaRecorder` (WebM/Opus) | Zero install for the doctor |
| Transcription | OpenAI direct: `gpt-4o-transcribe` | Better than Whisper for accents; no GPU needed |
| Note generation | Azure OpenAI chat deployment | Pluggable; reasoning-model aware |
| Patois research (Triage Lab) | facebook/mms-1b-l1107, optional facebook/omnilingual-asr-*, google/flan-t5-base, **Qwen/Qwen3-1.7B** (local interpreter) | Local, admin-only sandbox |
| Speaker diarization | `diarize` lib (CPU-friendly) or `pyannote.audio` 3.1 | Optional, only when both clinician + patient speak |
| Audio denoise | DeepFilterNet (preferred) or noisereduce fallback | Pre-MMS noise reduction |
| Auth | Django auth + `EmailOrUsernameBackend` + RBAC role | Doctors can sign in with email or username |
| Logging | Rotating file logs (app + audit) | Compliance trail for every session event |
| Models packaging | HuggingFace cache (`~/.cache/huggingface/hub/`) or `<BASE_DIR>/models/<slug>/` local override | Standard, plus an escape hatch for slow-internet manual installs |

---

## 2. Repository tour — what every folder/file does

```
WellnestScribe/
├── PROJECT_CONTEXT.md      (this file) Master orientation doc
├── ARCHITECTURE.md         Component diagram + deployment options + roadmap
├── README.md               Quickstart + AI config table + RBAC + Triage models
├── TRIAGE_INSTALL.md       pip-install matrix for Triage features (torch+CUDA, denoise, diarize, models)
├── manage.py               Django entry point
├── requirements.txt        Python deps (Django, decouple, openai, qrcode, …)
├── .env                    Local secrets (gitignored) — DJANGO_SETTINGS_MODULE=wellnest.settings
├── .env.example            Template for new contributors
├── .gitignore              Excludes .venv, .env, db.sqlite3, media, logs, pyc, models/
├── db.sqlite3              Legacy dev DB (current prod = MySQL via DATABASE_URL)
├── logs/                   Rotating file handlers write here (gitignored)
│   ├── wellnest.log        Application log
│   └── audit.log           SessionEvent audit trail (HIPAA/GDPR)
├── media/                  User uploads (gitignored)
│   ├── scribe_audio/<Y>/<M>/<D>/  Per-session audio
│   └── triage/             Triage Lab raw uploads (admin only)
├── models/                 Project-local fallback for HF model weights (gitignored).
│   └── <slug>/             e.g. Qwen--Qwen3-1.7B/ or google--gemma-4-E2B/
├── body diagram.PNG        Source asset (kept as reference); copy is at static/images/body-diagram.png
│
├── admin/                  ⚠ Reback HTML reference. Untouched. Don't edit.
├── assets/                 ⚠ Original Reback assets. Untouched.
│
├── apps/                   All Django apps live here (added to sys.path).
│   ├── accounts/           Auth + DoctorProfile + RBAC
│   │   ├── models.py       DoctorProfile (role, specialty, theme, prefs, suggestive_assist, custom_instructions)
│   │   ├── views.py        signin / signup / signout / profile / bootstrap_admin
│   │   ├── forms.py        WellnestSignInForm / WellnestSignUpForm / DoctorProfileForm
│   │   ├── urls.py         /accounts/* routes
│   │   ├── admin.py        Doctor profile admin (role editable inline)
│   │   ├── backends.py     EmailOrUsernameBackend — login with either
│   │   ├── apps.py         AccountsConfig
│   │   ├── migrations/     incl. 0003_repair_mysql_schema, 0004_doctorprofile_suggestive_assist
│   │   └── management/commands/
│   │       ├── promote.py  python manage.py promote <user> --role admin --staff
│   │       └── demote.py   Reverse of promote
│   │
│   └── scribe/             Sessions, notes, AI services, Triage Lab
│       ├── models.py       ScribeSession / SOAPNote / NoteShare / SessionEvent
│       │                   New fields (May 2026):
│       │                     ScribeSession.patient_name      (free-text)
│       │                     ScribeSession.patient_identifier (DOB/ID/etc.)
│       │                     ScribeSession.active_conditions  (csv of dm/htn/lipids/ckd/…)
│       │                     SOAPNote.body_markers            (JSON list)
│       │                     SOAPNote.wound_chart             (JSON dict — NATVNS top-level)
│       ├── views.py        Page views (Record/Review/History/Triage/Audit/Compliance)
│       │                   + JSON API (transcribe, generate, save, finalize, share,
│       │                     improve, polish, triage_run, triage_job_status,
│       │                     triage_install, triage_install_audio, triage_download,
│       │                     triage_probe, triage_interpret, triage_score)
│       ├── urls.py         /scribe/* routes (page + /api/* + /share/<token>)
│       ├── admin.py        SOAPNote/Session/SessionEvent admin
│       ├── apps.py         ScribeConfig
│       ├── context_processors.py   ui_preferences (theme, font, triage_visible,
│       │                           is_admin, ui_asset_version for cache-bust)
│       ├── migrations/     0001-0007 (current head: 0007 patient + body_markers)
│       │
│       ├── services/       AI + audio service layer (the brain)
│       │   ├── prompts.py          MASTER + JAMAICAN_CONTEXT + SUGGESTIVE_ASSIST +
│       │   │                       SOAP/NARRATIVE/CHART user prompts + section + verifier
│       │   │                       + PATOIS_INTERPRETER_SYSTEM_PROMPT
│       │   ├── clients.py          OpenAI + AzureOpenAI lazy clients (cached)
│       │   ├── transcription.py    gpt-4o-transcribe wrapper with medical priming
│       │   ├── soap_generator.py   generate_note + polish_grammar +
│       │   │                       suggest_improvements + interpret_patois +
│       │   │                       reasoning-model retry + refusal-pattern retry
│       │   ├── pipeline.py         run_transcription / run_note_generation /
│       │   │                       run_polish_grammar / run_interpret_patois — wraps
│       │   │                       real AI vs stub fallback
│       │   ├── stub.py             Deterministic offline responses for SCRIBE_USE_REAL_AI=False
│       │   ├── export.py           QR code + share link + WhatsApp deep link
│       │   ├── triage.py           Lazy MMS / FLAN-T5 / Omni-ASR / Qwen-Gemma loaders +
│       │   │                       probe_environment + _resolve_local_model_dir
│       │   ├── triage_jobs.py      In-memory job registry for background runs
│       │   ├── diarize_service.py  Speaker diarization (diarize lib + pyannote fallback)
│       │   ├── denoise.py          DeepFilterNet / noisereduce audio cleanup
│       │   └── metrics.py          WER + clinical safety + reliability score
│       │
│       └── management/commands/
│           ├── purge_audio.py              Retention purge (>30 days)
│           └── download_triage_models.py   Pre-cache MMS + T5 weights
│
├── templates/              Django templates (DIRS includes this).
│   ├── base.html           Authenticated app shell. Sidebar + topbar + content + scripts.
│   │                       Cache-busts CSS/JS via {{ ui_asset_version }} query param.
│   ├── base_auth.html      Auth shell (no sidebar). Used by signin/signup/share-expired.
│   │                       Also loads PWA manifest + service worker for installable app.
│   ├── landing.html        Public landing page for unauthenticated visitors.
│   ├── manifest.webmanifest        PWA manifest (server-rendered, has icons + colors)
│   ├── service-worker.js   PWA service worker (cache-first strategy for static assets)
│   ├── partials/
│   │   ├── topbar.html             Theme toggle + display settings + user menu
│   │   ├── sidebar.html            Desktop main-nav (.main-nav) — wraps _nav_items
│   │   ├── mobile_sidebar.html     Bootstrap offcanvas-bottom — wraps _nav_items
│   │   └── _nav_items.html         Shared nav items (Workspace + Admin + Account)
│   ├── accounts/
│   │   ├── signin.html             Email-or-username login
│   │   ├── signup.html             Username + email + specialty + facility
│   │   └── profile.html            DoctorProfileForm + bootstrap-admin banner +
│   │                               Triage access hint
│   └── scribe/
│       ├── record.html             Record screen — quick templates pills,
│       │                           note-style pills (SOAP/Narrative/Chart),
│       │                           suggestive-assist chip, recorder shell, length
│       │                           toggle, upload audio, PATIENT NAME + IDENTIFIER,
│       │                           ACTIVE CONDITIONS multi-checkbox pills, manual
│       │                           transcript, Generate from text, Recent sessions
│       ├── review.html             Editable title + Structured/Narrative/Transcript/
│       │                           Body diagram tabs + autosave + Copy/QR/WhatsApp/
│       │                           Polish/Print/Finalize. Body Diagram tab gets a
│       │                           "recommended" badge when conditions include
│       │                           dm/ckd or markers already exist.
│       ├── _soap_fields.html       Reusable S/O/A/P field block with quick-mic
│       ├── history.html            Session list with search filter
│       ├── triage.html             Audio in + Backend dropdown + Denoise/Diarize toggles +
│       │                           Run + raw output + diarized panel + interpret
│       │                           (Azure cloud OR local Qwen) + env probe + install
│       │                           + Reliability scoring + Conversation mode
│       ├── audit_log.html          Last 200 SessionEvents with type/user filter
│       ├── compliance.html         Metrics cards + active controls table
│       ├── share.html              Public read-only shared note view
│       └── share_expired.html      "Link expired" page
│
├── static/                 STATICFILES_DIRS = [BASE_DIR / "static"]
│   ├── css/
│   │   ├── vendor.min.css          Bootstrap + plugins (from Reback)
│   │   ├── icons.min.css           Iconify CSS (from Reback)
│   │   ├── app.min.css             Reback app styles
│   │   └── wellnest.css            ⭐ Custom overrides — fonts, blue palette,
│   │                               record-cta, recorder-shell, quick-templates-bar,
│   │                               note-style-pill, suggestive-assist-chip,
│   │                               session-row, mobile bottom-sheet, auth/landing,
│   │                               note-textarea, editable-title, quick-mic-helper,
│   │                               wellnest-toast, qr-canvas-wrap, page-back-btn,
│   │                               body-diagram-wrap / body-marker (NATVNS overlay),
│   │                               quick-pill (with :has(input:checked) state)
│   ├── js/
│   │   ├── vendor.js               Bootstrap + plugins
│   │   ├── app.js                  Reback baseline JS
│   │   ├── config.js               Reback theme config
│   │   └── wellnest.js             ⭐ Custom — single IIFE.
│   │                               Sections (search 'console.log("[wellnest]'):
│   │                                 1. helpers ($, postJSON, postForm, showToast)
│   │                                 2. theme + font scale + preferences
│   │                                 3. session search filter
│   │                                 4. idle timeout + auto-signout
│   │                                 5. record screen (MediaRecorder + waveform +
│   │                                    upload + patient identity + condition pills)
│   │                                 6. review screen (autosave + tab sync + share +
│   │                                    polish + body-diagram NATVNS cards)
│   │                                 7. triage screen (audio + backend + job poll +
│   │                                    install + interpreter switch + conversation mode)
│   │                                 8. quick-edit mics (SpeechRecognition + server fallback)
│   ├── images/             Reback images + wellnest-logo.png + body-diagram.png + pwa/
│   ├── fonts/              Boxicons fonts
│   └── vendor/             fullcalendar, gmaps, gridjs, jsvectormap (from Reback)
│
└── wellnest/               Django project package
    ├── settings.py         All config. python-decouple reads from .env.
    │                       Sections: env-driven core, INSTALLED_APPS, MIDDLEWARE,
    │                       TEMPLATES (with scribe.context_processors.ui_preferences),
    │                       DATABASE_URL parsing, AUTHENTICATION_BACKENDS, security
    │                       headers, SCRIBE_* env vars, TRIAGE_* env vars, LOGGING.
    ├── urls.py             Root router. / = landing-or-redirect; /admin/, /accounts/,
    │                       /scribe/, /manifest.webmanifest, /service-worker.js.
    ├── pwa.py              Serves PWA manifest + service worker views.
    ├── production.py       Production settings (deploy target uses this).
    ├── wsgi.py             WSGI entry
    └── asgi.py             ASGI entry
```

---

## 3. Data model — what gets stored

```
User (Django auth)                    ScribeSession                          SOAPNote (1:1 with Session)
  │ ├─ DoctorProfile                    ├─ doctor (FK User)                    ├─ subjective / objective / assessment / plan
  │ │   ├─ role  (clinician|lead|admin) ├─ title (editable inline)             ├─ narrative (free-form mode)
  │ │   ├─ specialty                    ├─ chief_complaint                     ├─ full_note (assembled)
  │ │   ├─ default_note_style           ├─ patient_name             (NEW)      ├─ edited_note (after doctor edits)
  │ │   ├─ long_form_default            ├─ patient_identifier       (NEW)      ├─ flags (json — [ALERT], [HERB-DRUG])
  │ │   ├─ font_scale (80..160)         ├─ active_conditions  csv   (NEW)      ├─ body_markers  JSON list (NEW)
  │ │   ├─ theme (light|dark|auto)      ├─ audio_file (auto-deleted at 30d)    ├─ wound_chart   JSON dict (NEW)
  │ │   ├─ suggestive_assist            ├─ duration_seconds                    ├─ review_completed
  │ │   └─ custom_instructions          ├─ session_type (dictation|text)       ├─ export_count
  │ │                                   ├─ note_format (soap|narrative|chart)
  │ └─ (auth fields)                    ├─ length_mode (normal|long_form)     NoteShare (1:N from Session)
                                        ├─ status (draft|transcribing|...)     ├─ token (unique, urlsafe)
                                        ├─ error_message                       ├─ expires_at (now + 1h)
                                        ├─ transcript                          ├─ opened_count
                                        ├─ created_at / updated_at /
                                        │  finalized_at
                                        └─ events ───────► SessionEvent (1:N)
                                                            ├─ event_type
                                                            ├─ detail
                                                            └─ created_at
```

The audit log mirrors `SessionEvent` rows into `logs/audit.log` via the `scribe.audit` logger.

### `body_markers` schema (one entry per wound/site)

```python
{
    "x": 42.3,                # percent of image width  (survives resizing)
    "y": 67.1,                # percent of image height
    "wound_type": "diabetic", # leg_ulcer | surgical | diabetic | pressure | other
    "duration": "3 weeks",    # free text
    "length_cm": "2", "width_cm": "1.5", "depth_cm": "0.4", "tracking_cm": "0",
    "tissue_necrotic": "10", "tissue_slough": "20", "tissue_granulating": "60",
    "tissue_epithelialising": "10", "tissue_hypergranulating": "0",
    "tissue_haematoma": "0",  "tissue_bone_tendon": "0",     # percentages, total 100
    "exudate": "wet",          # dry | wet | saturated
    "exudate_type": "serous",  # serous | haemoserous | cloudy | green_brown
    "peri_wound": ["macerated"],         # multi-select tag list
    "infection_signs": ["heat", "increasing_pain"],
    "treatment_goal": "absorption",      # debridement | absorption | hydration | …
    "analgesia": "predressing",          # none | predressing | regular
    "notes": "Refer to TVN",
}
```

Old marker dicts (just `size_cm`/`exudate`/`notes` from the first cut) still load — missing keys are treated as blank.

### `wound_chart` schema (top-level — applies to whole patient)

```python
{
    "factors_delaying_healing": ["diabetes", "anaemia", "medication"],
    "allergies": "iodine, latex",
}
```

---

## 4. Request flow — typical doctor session

```
RECORD SCREEN                                    REVIEW SCREEN
───────────────                                  ──────────────
1. MediaRecorder captures WebM/Opus              5. /sessions/<id>/review/ renders
2. POST /scribe/api/sessions/                        - tabs: Structured / Narrative /
   (multipart)                                         Transcript / Body diagram
   - audio + format + length                       6. Doctor edits inline. Autosave fires
   - patient_name + patient_identifier                1.1 s after last keystroke.
   - active_conditions csv                         7. Body Diagram tab: click on image
   → ScribeSession(status='draft')                    drops a marker; NATVNS card opens
3. POST /scribe/api/sessions/<id>/transcribe/         on the right; auto-saves.
   → run_transcription() → gpt-4o-transcribe       8. Optional: Polish grammar / Check
   → session.transcript                               missing (suggestive only) / QR
4. POST /scribe/api/sessions/<id>/generate/           share / WhatsApp / Print.
   → run_note_generation() → Azure OpenAI          9. POST /scribe/api/sessions/<id>/
   → detects refusal/empty + retries                  finalize/
   → splits S/O/A/P                                10. SessionEvent rows + audit.log
   → SOAPNote persisted                                appended at every step.
   → status='review' → redirect to review
```

---

## 5. AI architecture (_internal_ — do not publish)

### Provider abstraction
`apps/scribe/services/clients.py` defines two lazy clients:
- `get_transcription_client()` — OpenAI direct, uses `SCRIBE_OPENAI_API_KEY`
- `get_chat_client()` — AzureOpenAI, uses `SCRIBE_AZURE_OPENAI_*`

Both are `@lru_cache(maxsize=1)`.

### Prompt layers (in `apps/scribe/services/prompts.py`)
1. `MASTER_SYSTEM_PROMPT` — universal extraction rules. Note: prohibits "rule out", "consider", workup suggestions by default.
2. `SUGGESTIVE_ASSIST_ADDENDUM` — appended only when doctor enables the chip on the record screen.
3. `JAMAICAN_CONTEXT_ADDENDUM` — Jamaican meds, herbs, Patois phrases.
4. `specialty_addendum(specialty)` — anesthesia / OB-GYN / paediatrics / etc.
5. Doctor's `custom_instructions`.
6. User prompt — `SINGLE_SOAP_USER_PROMPT` (default) or `SINGLE_SOAP_USER_PROMPT_SUGGESTIVE` (when chip on). Plus `NARRATIVE_USER_PROMPT` / `CHART_USER_PROMPT` (with worked examples).

### Reasoning-model retries
`_chat()` in `soap_generator.py` detects deployments with names containing `gpt-5`, `o1`, `o3`, `o4`, `reasoning`. Sends `reasoning_effort=minimal` first; on empty output, retries with double budget + `reasoning_effort=low`. Logs `reasoning_tokens` + `completion_tokens` per call.

### Refusal-pattern recovery
`_looks_like_refusal()` — when ≥ 3 of 4 SOAP sections are `Not documented` and transcript > 60 chars, replays the over-conservative response back as `assistant` and demands extraction.

### Azure content-filter workaround (Patois interpreter)
**Critical nuance.** Azure's content filter flags raw Patois ASR output as "sexual high" because phonetic tokens like `naip`, `fingga`, `beli`, `batam` lack medical context when scanned in isolation as a system message. Fix: **concatenate the `PATOIS_INTERPRETER_SYSTEM_PROMPT` into the user message body** so the filter scans the medical framing + the Patois as a single block. The system message is kept minimal ("You are a licensed medical interpreter…"). Both Azure and local Gemma/Qwen use the same trick — see `interpret_patois()` in `soap_generator.py`.

### Local interpreter (Triage Lab)
Default model id is **Qwen/Qwen3-1.7B** (was `google/gemma-4-E2B` — Gemma underperformed for Patois). Override via the "Local model id" input in section 4 of the Triage page. Resolution order: `<BASE_DIR>/models/<slug>/` → `<BASE_DIR>/models/<short>/` → HuggingFace hub. The Gemma path still works if you put weights in `models/google--gemma-4-E2B/`.

---

## 6. RBAC — who sees what

| Role | Sidebar items | Triage Lab | /admin/ | Audit + Compliance |
|---|---|---|---|---|
| `clinician` (default) | New session, Sessions, Profile | no | no | no |
| `lead` | + Triage | yes | no | no (unless `is_staff`) |
| `admin` | + Audit + Compliance + Django admin | yes | yes (when also `is_staff`) | yes |

Switching roles:
- CLI: `python manage.py promote <user> --role admin --staff --superuser`
- Admin: Doctor profiles → role column is editable inline
- First-run: profile page shows "Make me the first admin" banner if no admin exists yet

**Two distinct visibility gates inside Triage:**
- `_triage_visible(user)` — can SEE the page (env flag + role)
- `_triage_admin(user)` — can perform privileged actions (pip install, model download) — admin-only regardless of `SCRIBE_ENABLE_TRIAGE` because pip install is arbitrary code execution.

---

## 7. Triage Lab (admin / staff sandbox)

**Purpose.** Internal research surface for testing on-device Patois ASR + interpretation.

**Backends** (section 2 of the Triage page — these run on audio):
- `mms` — facebook/mms-1b-l1107 with `target_lang=jam`
- `omni` — any HuggingFace speech model id (Meta omnilingual-asr-* / seamless-m4t / etc.)
- `t5_paraphrase` — google/flan-t5-base text rewrite

**Interpreters** (section 4 — these turn Patois text into clinical English):
- `azure` (default) — Azure OpenAI deployment with PATOIS_INTERPRETER_SYSTEM_PROMPT
- `gemma_local` — Qwen3-1.7B by default (override in the "Local model id" input). Same Patois prompt as Azure; runs on CPU/CUDA.

**Optional preprocessing/postprocessing:**
- Denoise (DeepFilterNet / noisereduce) BEFORE transcription. Toggle in section 2.
  Hint shown to user: applied AFTER recording stops, before ASR. Not real-time.
- Speaker diarization AFTER transcription. Output shown in a separate panel with
  `SPEAKER_1 [00:00–00:42]: …` labels. When the toggle is on but pyannote/diarize
  isn't installed, the panel renders an explicit `[diarization did not run]` message.

**Job model.** Backends run in background threads via `triage_jobs.py`. Client polls `/api/triage/jobs/<job_id>/` every 2 s for `stage` + `status` + `result`.

**Conversation mode.** Toggle in the Triage header top-right hides the step-by-step grid and shows a single record button that runs the full pipeline (denoise → ASR → diarize → interpret) and only displays the final clinical English + total elapsed.

**Reliability scoring (section 5).** WER (Track 1) + LLM-judged semantic + negation accuracy (Track 2) + clinical safety flags (Track 3). Reliability Score = 0.4·sem + 0.4·neg + 0.2·(1−err). Target ≥ 0.90 before pilot.

---

## 8. Compliance posture

| Control | Where |
|---|---|
| Secure cookies (`SECURE` when not DEBUG, `HttpOnly`, `SameSite=Lax`) | `wellnest/settings.py` |
| 8h absolute session, rolling on activity | `SESSION_*` settings |
| 15-minute idle warning + auto-signout | `wellnest.js` initIdleTimeout |
| HSTS + SSL redirect when not DEBUG | settings.py guarded by `if not DEBUG` |
| `X-Frame-Options: DENY`, no-sniff, strict referrer | `SECURE_*` settings |
| Audit log (DB + rotating file) | `_log()` in `scribe/views.py` + `scribe.audit` logger |
| Audio retention purge | `python manage.py purge_audio` (cron / Task Scheduler) |
| AI disclaimer on every note | Appended in prompts + UI footer |
| RBAC | `accounts/models.py` `DoctorProfile.role` + `_triage_admin` gate |
| PHI minimisation | Patient name + identifier are OPTIONAL. Pilot rule: initials + DOB only. |

---

## 9. Common dev tasks — where to look

| Task | File |
|---|---|
| Change a prompt | `apps/scribe/services/prompts.py` |
| Add a new note format | prompts + `generate_note()` in soap_generator + `note_format` field choices |
| Swap chat provider | `apps/scribe/services/clients.py` + `.env` |
| Add a new sidebar item | `templates/partials/_nav_items.html` (use `request.path` for active state) |
| Add an admin-only view | check `_triage_admin(user)` or `user.is_staff` in the view, conditional render in nav |
| Add a CSS rule | `static/css/wellnest.css` (loaded after Reback's app.min.css, so overrides win) |
| Add a JS handler | `static/js/wellnest.js` — single IIFE; scope by `data-screen='X'` + `$(sel, root)` |
| New management command | `apps/<app>/management/commands/<name>.py`, subclass `BaseCommand` |
| Add a setting | `wellnest/settings.py` via `decouple.config(...)` so it picks up from `.env` |
| Touch the data model | edit models.py → `python manage.py makemigrations <app>` → `migrate` |
| Add a Patois phrase mapping | `JAMAICAN_CONTEXT_ADDENDUM` + `PATOIS_INTERPRETER_SYSTEM_PROMPT` |
| Switch local interpreter model | Triage section 4 → Local model id input (or env override) |

---

## 10. Conventions / patterns to preserve

- **Lazy ML imports.** All heavy deps (`torch`, `transformers`, `librosa`, `pyannote`) imported INSIDE the function that needs them. Surfaces missing deps as a 503 with pip command instead of crashing app startup.
- **Stub fallback.** Every AI call goes through `pipeline.py` which checks `SCRIBE_USE_REAL_AI` and falls back to deterministic stubs. UI always works without keys.
- **Background jobs for slow paths.** Triage runs in threads tracked by `triage_jobs.py`. Poll `/api/triage/jobs/<id>/`.
- **Audit every state change.** Use `_log(session, event_type, detail)` — writes both DB row and rotating file.
- **Plain text in clinical output.** No markdown — doctors paste into EHR text fields. Enforced in prompts + `_split_soap()` regex.
- **Mobile-first nav.** Desktop sidebar `.main-nav` is hidden under 992 px; mobile uses Bootstrap `offcanvas-bottom`. Don't put `data-bs-dismiss="offcanvas"` on desktop links — it intercepts clicks.
- **Cache-bust in dev AND prod.** `{{ ui_asset_version }}` (max mtime of wellnest.css/js + service-worker.js + pwa.py) appended as `?v=…` to `wellnest.css` and `wellnest.js`. Updates whenever you edit those files, so deployed users get fresh code without a hard refresh.
- **Single source of truth for nav.** `_nav_items.html` is included in both desktop sidebar and mobile sheet.
- **Comments in Django templates use `{% comment %} ... {% endcomment %}`** for multi-line. `{# ... #}` is single-line only — don't span lines.
- **CSRF.** All mutating endpoints use `@csrf_protect`. Frontend reads token from `window.WELLNEST.csrfToken` and sends `X-CSRFToken` header.
- **Soft auth backend.** `EmailOrUsernameBackend` accepts either; `signup_view` must pass explicit `backend="...ModelBackend"` to `login()` since multiple backends are configured.
- **PWA cache-bust.** Service worker registration uses the same `?v=` token so iOS/Android update the worker when assets change.

---

## 11. What lives off-server (cloud APIs)

- **Speech-to-text** — OpenAI direct, model `gpt-4o-transcribe`. ~$0.006/min.
- **Chat completion** — Azure OpenAI deployment. Per-token cost depends on the deployment.
- **Models cached on server (not browser)** — HuggingFace models for Triage live in `~/.cache/huggingface/hub/` or `<BASE_DIR>/models/`. Doctor's device downloads nothing.

---

## 12. What's NOT in this repo

- Patient names by default. Optional fields exist (`patient_name`, `patient_identifier`) but pilot guidance says use initials + DOB only.
- Patient-identifying audio (auto-purged after `AUTO_DELETE_AUDIO_DAYS`).
- Production secrets. `.env` is gitignored.
- Background job queue (Celery/Django-Q) — runs in threads for now; swap when you scale past a few doctors.
- Real EHR integration. QR-share-link is the bridge.

---

## 13. If you're a coding agent reading this

1. Don't touch `admin/` or `assets/` — those are the Reback reference, immutable.
2. Don't auto-download models (5+ GB). Use the management command, the in-UI button, or drop weights into `<BASE_DIR>/models/<slug>/`.
3. Stub mode (`SCRIBE_USE_REAL_AI=False`) is the default for tests. Real keys live in `.env`.
4. Multi-line template comments: `{% comment %} ... {% endcomment %}`. Anywhere else use single-line `{# ... #}`.
5. New ML deps → lazy-load inside the function. Probe with `probe_environment()` pattern.
6. Sidebar nav items: link must work without `data-bs-dismiss` (it breaks desktop clicks).
7. Privileged admin actions (pip install, model download) gate on `_triage_admin`, not `_triage_visible`.
8. After model/migration changes always run `python manage.py check`.
9. For interpret_patois / suggestive_assist / Azure-only calls — preserve the **system-prompt-inside-user-message** pattern for content-filter safety.

---

## 14. Gotchas we already paid for (don't re-step on these)

| Gotcha | Symptom | Fix |
|---|---|---|
| Azure content filter flags raw Patois | 400 BadRequest `code=content_filter`, "sexual high" | Inline `PATOIS_INTERPRETER_SYSTEM_PROMPT` into the user message body so it's scanned WITH the Patois. Keep `system` minimal. |
| Multi-line `{# ... #}` template comments | Comment text renders as visible body content in the sidebar | Use `{% comment %} ... {% endcomment %}` |
| `data-bs-dismiss="offcanvas"` on desktop nav links | Clicks navigate to `#` instead of the href | Don't put it on desktop sidebar links. Mobile offcanvas closes on page reload anyway. |
| Multi-backend `login()` after adding EmailOrUsernameBackend | `signup_view` raises "you have multiple authentication backends" | Pass `backend="django.contrib.auth.backends.ModelBackend"` explicitly to `login()` |
| `pip install ... --index-url cu12` | "ERROR: No matching distribution found for torch" | URL needs the 3-digit suffix (`cu121`, `cu124`, `cu126`) |
| CPU torch already cached → CUDA install no-ops | Probe still says "CUDA: no" after the install | Use `pip install --upgrade --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121`. There's a one-click button on the Triage page for this. |
| Reasoning models burn the token budget on internal CoT | Empty SOAP output, finish_reason=length | `_chat()` retries with double budget + `reasoning_effort=minimal` |
| Small reasoning models default to refusal | All 4 SOAP sections come back as "Not documented" | `_looks_like_refusal()` detects and replays the previous attempt back as `assistant` + demands extraction |
| Triage runs blocking the request thread | "Running…" frozen 10 min | Moved to background threads via `triage_jobs.py`; client polls `/jobs/<id>/` |
| HF cache symlinks fragile on Windows | Manual download fails to "register" with from_pretrained | Drop weights into `<BASE_DIR>/models/<slug>/` (e.g. `Qwen--Qwen3-1.7B`) — `_resolve_local_model_dir()` checks there before hitting the hub |
| MySQL orphan NOT-NULL columns from earlier schema iterations | `(1364, "Field '<x>' doesn't have a default value")` on INSERT. Hit on `encounter_alias`, `model_used`, etc. | Write a raw-SQL migration that drops the orphan via `information_schema.COLUMNS` lookup. See `0008_drop_orphan_session_columns.py` + `0009_drop_orphan_soapnote_columns.py`. Always vendor-gate (`if connection.vendor != "mysql": return`) so SQLite dev DBs no-op. **Before adding a column to the drop list, grep models.py to confirm it's truly orphan — over-dropping (e.g. `export_count`) requires a follow-up restore migration like `0010_restore_soapnote_export_count.py`.** |
| `body_diagram.PNG` had a space in the filename | Static serving 404 | Copied to `static/images/body-diagram.png` (no space) |
| pyannote 3.1 needs HF auth token + model T&C accept | 401 Unauthorized on first diarize | Run `huggingface-cli login` once and accept terms at huggingface.co/pyannote/speaker-diarization-3.1 |
| Browser caches old wellnest.js / .css | Bug "fixes" don't show until Ctrl+Shift+R | Both files get `?v={{ ui_asset_version }}` cache-busts; mtime-based, auto-updates on edit |

---

## 15. Recent changes (May 2026)

- **Switched from MySQL back to MySQL** as the prod DB. SQLite still works for local dev via empty `DATABASE_URL`.
- **PWA support** — manifest + service worker, doctors can install the app to their home screen.
- **Suggestive assist** — moved from a per-button feature to a per-doctor preference (chip on record screen, persisted on `DoctorProfile.suggestive_assist`). Gates the "Check missing details" button and switches the SOAP prompt to `SINGLE_SOAP_USER_PROMPT_SUGGESTIVE`. Default OFF — consultants don't want suggestive features (Dr Elizabeth + Dr Smith feedback).
- **Note-style pills** moved to the top of the record card. SOAP / Narrative / Chart, single-select.
- **Patient identity capture** — optional `patient_name` + `patient_identifier` fields on the record screen and `ScribeSession`. `display_title` joins them.
- **Active conditions multi-checklist** — diabetes, hypertension, lipids, CKD, obesity, IHD, CCF, asthma/COPD, thyroid, depression. Stored as csv on `ScribeSession.active_conditions`. Used to recommend the body-diagram tab on review.
- **Body diagram annotation** (Dr Elizabeth feedback) — new tab on Review screen with the NATVNS Wound Management chart embedded. Click on `static/images/body-diagram.png` to drop a marker; one card per marker captures wound type, dimensions, tissue type %, exudate level + type, peri-wound skin tags, signs of infection, treatment goal, analgesia, notes. Top-level "Factors delaying healing" checkboxes apply per patient. All persisted via `SOAPNote.body_markers` + `SOAPNote.wound_chart`. Tab shows a "recommended" badge when `dm` / `ckd` is in `active_conditions` or markers already exist.
- **Local interpreter model** swapped from Gemma 4 E2B to **Qwen/Qwen3-1.7B** by default (Gemma underperformed). Override via the section-4 input.
- **Conversation mode** in Triage (header toggle) hides the step-by-step grid and runs the full pipeline end-to-end, showing only the final clinical English.
- **Drag-and-drop audio** onto the Triage recorder shell + upload button.
- **Waveform now actually pumps** during recording (analyser node wired).
- **TRIAGE_INSTALL.md** new file documents every pip command needed for the Triage stack.

---

*Last updated: 2026-05-06.*
