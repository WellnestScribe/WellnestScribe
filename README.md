# WellNest Scribe

Voice-to-clinical-notes for Caribbean healthcare. Django web app, mobile-first UI built on the Reback admin template, Azure OpenAI for SOAP/narrative/chart note generation, OpenAI `gpt-4o-transcribe` for speech-to-text.

## Project layout

```
WellnestScribe/
├── admin/                  Original Reback HTML reference (untouched).
├── assets/                 Original Reback assets (untouched).
├── apps/
│   ├── accounts/           Auth + DoctorProfile model + sign-in/sign-up views.
│   └── scribe/             Sessions, SOAP notes, AI services, views/URLs.
│       └── services/       prompts.py, clients.py, transcription.py, soap_generator.py, pipeline.py, stub.py
├── templates/              Django templates (base + partials + scribe + accounts).
├── static/
│   ├── css/                vendor.min.css, app.min.css, icons.min.css, wellnest.css
│   ├── js/                 app.js, vendor.js, config.js, wellnest.js
│   ├── images/             Reback images + wellnest-logo.png
│   ├── fonts/, vendor/
├── wellnest/               Django project (settings.py, urls.py, wsgi.py, asgi.py)
├── media/                  User-uploaded audio (gitignored)
├── manage.py
├── .env                    Local secrets (gitignored — see .env.example)
├── requirements.txt
└── README.md
```

## First-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Fill in the keys you need in .env (or copy .env.example)
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
python manage.py runserver 0.0.0.0:8000
```

Open http://127.0.0.1:8000/ — you'll be redirected to sign-in.

## AI configuration

The app reads `SCRIBE_*` keys from `.env`:

| Key | Purpose |
|---|---|
| `SCRIBE_USE_REAL_AI` | `True` to call cloud AI; `False` uses deterministic stub responses (good for UI/dev). |
| `SCRIBE_OPENAI_API_KEY` | OpenAI direct key. Used for `gpt-4o-transcribe` (audio → text). |
| `SCRIBE_OPENAI_TRANSCRIBE_MODEL` | Transcription model (default `gpt-4o-transcribe`). |
| `SCRIBE_AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint. |
| `SCRIBE_AZURE_OPENAI_KEY` | Azure OpenAI key. |
| `SCRIBE_AZURE_OPENAI_DEPLOYMENT` | Chat deployment name (e.g. `gpt-5-nano`, `gpt-4o-mini`). |
| `SCRIBE_AZURE_OPENAI_API_VERSION` | Defaults to `2024-12-01-preview`. |
| `SCRIBE_PIPELINE_MODE` | `single` (one call) or `modular` (one call per SOAP section). |
| `SCRIBE_VERIFIER_ENABLED` | Reserved for future verifier pass. |
| `SCRIBE_MAX_COMPLETION_TOKENS` | Hard cap per call. Default 1400. |

If a key is missing or `SCRIBE_USE_REAL_AI=False`, the pipeline falls back to a deterministic stub so you can still test the UI without burning credits.

## Features delivered (MVP)

- **Sign-in / sign-up** with per-doctor profile (specialty, facility, custom AI instructions).
- **Record screen**: big record button, MediaRecorder with live waveform, audio upload, or text-only entry. SOAP / Narrative / Chart formats. Normal vs. Long-form length mode.
- **Pipeline**: audio → `gpt-4o-transcribe` → Azure OpenAI chat → structured SOAP / narrative / chart note.
- **Review screen**: tabbed Structured / Narrative / Transcript views, inline editing, autosave, copy to clipboard, share via WhatsApp, finalize.
- **Quick-edit dictation**: per-section mic uses `webkitSpeechRecognition` to append speech directly into a field.
- **History**: chronological list of sessions.
- **Profile & preferences**: theme (light/dark/auto), font scale (80–160%), default note style, long-form default, custom instructions appended to AI prompts.
- **Mobile-first UI**: desktop sidebar collapses into a bottom-sheet (Bootstrap `offcanvas-bottom`) on screens < 992 px. Sidebar nav never shows the desktop slide-in on phone.
- **Responsive typography**: per-doctor font scaling via `data-font-scale` on `<html>`.

## What's not in the MVP yet

- WhatsApp / QR-code share link generation server-side (currently uses a `wa.me` deep link with the note text).
- Patois post-processing dictionary applied to transcripts.
- Verifier pass (`SCRIBE_VERIFIER_ENABLED`) — wiring exists; pipeline enable later.
- Edge / hurricane mode (`SCRIBE_MODE=edge`) — settings flag is present, implementation is future work.
- Background jobs / Celery — transcription + generation run synchronously inside the request for simplicity.

## Useful URLs

| Path | Purpose |
|---|---|
| `/` | Redirects to record screen (or sign-in). |
| `/accounts/signin/` | Sign in. |
| `/accounts/signup/` | Sign up. |
| `/accounts/profile/` | Profile + preferences. |
| `/scribe/` | Record screen. |
| `/scribe/sessions/` | History. |
| `/scribe/sessions/<id>/review/` | Review + edit a note. |
| `/admin/` | Django admin. |
