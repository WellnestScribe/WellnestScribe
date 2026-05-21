# WellnestScribe + GNU Health — System Architecture

*This document explains what WellnestScribe is, how it connects to GNU Health, how clinics would use it, and the business/licensing model. It is written for clinic owners and Ministry of Health partners first, with technical detail in the lower sections for IT teams.*

---

## Part 1 — For Clinic Owners and Ministry Partners

### What is WellnestScribe?

WellnestScribe is an AI-powered medical scribe. A doctor speaks during a consultation and WellnestScribe:

1. Transcribes the conversation in real time (using speech-to-text tuned for Jamaican English and Patois)
2. Generates a structured clinical note (SOAP format — Subjective, Objective, Assessment, Plan)
3. Saves that note directly into the clinic's patient record, so no typing is needed after the visit

**The problem it solves:** Doctors in Jamaican clinics spend 30–40% of their time on paperwork. WellnestScribe eliminates that — a doctor finishes a consultation, walks out, and the note is already written.

---

### What is GNU Health?

GNU Health is a free, open-source electronic medical record (EMR) system used internationally. It manages:
- Patient demographics and history
- Appointments and scheduling
- Prescriptions and drug interactions
- Lab results
- Encounters (visit notes)

It runs on any computer and has both a desktop application (Tryton) and a web browser interface. **It costs nothing** — there is no per-seat licence. This makes it ideal for resource-constrained Jamaican clinics.

---

### How WellnestScribe + GNU Health work together

Think of it as two applications that share a patient record:

```
Doctor speaks
      ↓
WellnestScribe transcribes + generates note
      ↓
Note is saved into GNU Health patient record automatically
      ↓
Doctor sees the complete, structured visit note in Tryton
```

The doctor never has to copy text between systems. WellnestScribe writes directly into GNU Health.

---

### Recommended deployment for clinics (hosted SaaS)

**The clinic needs zero IT infrastructure.** We host everything:

```
                    ┌─────────────────────────────────────┐
                    │         Azure Cloud (our servers)   │
                    │                                     │
                    │  ┌──────────────┐  ┌─────────────┐ │
Doctor's device ────┼─▶│ WellnestScribe│  │ GNU Health  │ │
(any browser or     │  │  (Django app) │◀▶│  (Tryton /  │ │
 Tryton desktop)    │  └──────────────┘  │ PostgreSQL)  │ │
                    │                    └─────────────┘ │
                    └─────────────────────────────────────┘
```

- Doctor's laptop/tablet connects to our cloud server — no software to install except (optionally) the free Tryton desktop client
- Patient data stays on our Azure-hosted server, backed up automatically
- Clinic pays a monthly subscription; we handle all maintenance and updates
- Disaster recovery and data redundancy are built in

**Alternative for large clinics:** We can deploy the stack on a local server inside the clinic (e.g. for Ministry of Health sites where data sovereignty requires on-premises storage). The doctor's computers connect over the clinic's internal network.

---

### What does the doctor's day look like?

1. Doctor opens Tryton (desktop or browser) → sees patient list
2. Clicks on a patient → the patient record opens
3. Clicks the **WellnestScribe tab** inside the patient record
4. Clicks **Record New Session** → WellnestScribe opens in a browser tab, pre-linked to that patient
5. Doctor speaks during the consultation
6. WellnestScribe generates the clinical note
7. Doctor reviews/edits and clicks **Push to GNU Health**
8. The encounter is saved automatically into the GNU Health patient record
9. Back in Tryton, the visit note is already there — no copy-paste, no manual entry

---

## Part 2 — Licensing and Business Model

### GPL-3.0 and what it means for us

GNU Health is licensed under GPL-3.0. The GPL requires that if you **distribute** a modified version of GNU Health, you must also release those modifications as open source.

**We do not modify GNU Health.** Instead, WellnestScribe integrates with it through two mechanisms:

1. **A REST API bridge** — WellnestScribe calls GNU Health's standard XML-RPC API. This is like calling a phone; you don't need the phone's source code.
2. **A Tryton plugin module** (`health_wellnest`) — This is our own code, written alongside GNU Health, not derived from it. It is analogous to a Microsoft Word add-in: the add-in is not subject to Word's licence.

**Our code is proprietary.** The `health_wellnest` plugin, the Django scribe application, and the AI pipeline are all WellnestScribe IP. We are not required to open-source any of it.

---

### Subscription model

| Tier | Target | Includes |
|------|--------|----------|
| Clinic Basic | 1–5 doctors | Scribe + GNU Health hosting + 50 GB storage |
| Clinic Pro | 5–20 doctors | + Priority support + custom templates |
| Ministry / Hospital | 20+ doctors | + On-premises option + SLA + training |

GNU Health itself has no licence cost — the subscription covers our hosting, AI API usage (OpenAI/Azure), support, and the WellnestScribe software.

---

## Part 3 — Technical Architecture

### System components

```
┌─────────────────────────────────────────────────────────┐
│  WellnestScribe (Django 5.0.6, Python 3.12)             │
│  ┌───────────────┐  ┌──────────────────────────────┐   │
│  │ Scribe Engine │  │ EMR Bridge Layer              │   │
│  │ - Audio→Text  │  │ apps/emr/backends/            │   │
│  │ - AI note gen │  │   gnuhealth_backend.py ──────┼──▶│
│  │ - Review/edit │  │   local_backend.py           │   │
│  └───────────────┘  │   registry.py                │   │
│                     └──────────────────────────────┘   │
└────────────────────────────────┬────────────────────────┘
                                 │ XML-RPC (port 8069)
                                 ▼
┌─────────────────────────────────────────────────────────┐
│  GNU Health 5.0.6 / Tryton 7.0 (Docker container)      │
│  ┌───────────────────┐  ┌──────────────────────────┐   │
│  │ health_wellnest   │  │ Core GNU Health modules   │   │
│  │ (our Tryton       │  │ - gnuhealth.patient       │   │
│  │  plugin)          │  │ - gnuhealth.patient.      │   │
│  │ Adds tab to       │  │     evaluation            │   │
│  │ patient form      │  │ - party.party             │   │
│  └───────────────────┘  └──────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ PostgreSQL 16 (separate container)              │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Integration point 1 — REST/XML-RPC bridge (Django → GNU Health)

File: [apps/emr/backends/gnuhealth_backend.py](../apps/emr/backends/gnuhealth_backend.py)

The bridge uses Tryton's standard XML-RPC protocol (`xmlrpc.client`). It:

1. Authenticates with `common.login(db, user, password)` → receives a session token
2. Calls `object.execute(db, uid, token, model, method, args)` to read/write records
3. Caches the session token (thread-safe) and retries on expiry

**API endpoints exposed by WellnestScribe:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/emr/api/gnuhealth/status/` | GET | Check connection to GNU Health |
| `/emr/api/gnuhealth/patients/?q=Smith` | GET | Search patients |
| `/emr/api/gnuhealth/sessions/<id>/push/` | POST | Push a scribe session as an encounter |

**Config in `.env`:**
```
EMR_BACKEND=gnuhealth
GNUHEALTH_HOST=localhost
GNUHEALTH_PORT=8069
GNUHEALTH_DB=gnuhealth
GNUHEALTH_USER=admin
GNUHEALTH_PASSWORD=change_me_before_deploy
```

### Integration point 2 — Tryton module (GNU Health → WellnestScribe)

Directory: [gnuhealth/modules/health_wellnest/](../gnuhealth/modules/health_wellnest/)

This is a standard Tryton module that:
- Adds a `gnuhealth.wellnest.session` model (stores session references)
- Extends `gnuhealth.patient` with a `wellnest_sessions` One2Many and a `wellnest_record_url` function field
- Injects a **WellnestScribe tab** into the patient form view (via XPath extension)
- Renders a clickable URL that opens WellnestScribe pre-linked to that patient

**Module structure:**
```
gnuhealth/modules/health_wellnest/
├── tryton.cfg              ← module metadata + dependency declarations
├── __init__.py             ← registers models with the Tryton pool
├── health_wellnest.py      ← Patient extension + WellnestSession model
├── view/
│   ├── patient_form_extend.xml     ← adds WellnestScribe tab to patient form
│   ├── wellnest_session_tree.xml   ← list view for sessions
│   └── wellnest_session_form.xml   ← detail view for a single session
└── locale/
    └── en.po               ← English field labels
```

### Installing the Tryton module into the Docker container

The module is automatically copied into the container during `docker compose up --build` (the Dockerfile `COPY modules/ /modules/` step). The entrypoint symlinks it into trytond's module directory on startup.

**First-time activation in Tryton admin:**

1. In Tryton desktop: **Administration → Modules → Modules**
2. Search for `health_wellnest`
3. Click **Activate**, then confirm the upgrade
4. The WellnestScribe tab will appear on all patient records immediately

**Re-deploying updates:** Just rebuild the Docker image and restart — `docker compose up --build -d`. The entrypoint runs `trytond-admin --update all` on subsequent starts.

---

## Part 4 — Local Dev Credentials

| System | URL | Username | Password |
|--------|-----|----------|---------|
| WellnestScribe | http://localhost:9093/ | your Django admin | (set at createsuperuser) |
| GNU Health web status | http://localhost:8069/ | — | — |
| Tryton desktop | localhost:8069 | admin | `change_me_before_deploy` |
| GNU Health PostgreSQL | localhost:5433 | gnuhealth | `gnuhealth_secret` |

**Starting the stack:**
```powershell
# Terminal 1 — WellnestScribe
cd "c:\xampp\htdocs\WellnestScribe"
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:9093

# Terminal 2 — GNU Health
cd "c:\xampp\htdocs\WellnestScribe\gnuhealth"
docker compose up -d
```

See [RUNBOOK.md](../RUNBOOK.md) for the full daily startup guide and troubleshooting.

---

## Part 5 — Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Django scribe app with local EMR | Done |
| 2 | GNU Health Docker integration + XML-RPC bridge | Done |
| 3 | `health_wellnest` Tryton plugin — patient form tab | Done (needs activation) |
| 4 | Azure hosting — multi-tenant deployment | Planned |
| 5 | Ministry of Health pilot — 2–3 clinics | Planned |
| 6 | Drug interaction checking inside scribe note | In progress |
| 7 | Offline mode (local-first sync) | Planned |
