# WellnestScribe — Emergency Department Workflow System
## Architecture & Implementation Plan

> Modeled after the **Mercer General Hospital ED** (Caribbean regional facility, ~80,000 catchment population, 70–170 patients/day). Built to complement GNU Health as a real-time clinical workflow layer, not a replacement EMR.

---

## 1. Clinical Context

### ED Volume & Acuity Profile
| Metric | Value |
|---|---|
| Daily visits | 70 – 170 |
| Catchment population | ~80,000 |
| ESI 1–2 (critical/emergent) | ~10% |
| ESI 3 (urgent) | ~35% |
| ESI 4–5 (lower acuity) | ~55% |

### The Five Critical Timestamps
Every ED encounter tracks five mandatory timestamps. These drive length-of-stay metrics, triage target compliance, and accreditation reporting.

| # | Timestamp | Clock starts when… | Target |
|---|---|---|---|
| 1 | **Arrival** | Patient registers at desk or ambulance unloads | t=0 |
| 2 | **Triage complete** | Triage nurse saves ESI assessment | < 15 min from arrival |
| 3 | **Door-to-doctor** | Physician opens patient chart and begins assessment | < 30 min ESI 1–2 / < 60 min ESI 3 |
| 4 | **Disposition decision** | Attending clicks "Decide disposition" | — |
| 5 | **Exit** | Patient physically leaves the department | — |

### Zones
| Zone | Capacity | ESI Targets | Color |
|---|---|---|---|
| Resuscitation | 2 bays | ESI 1 | Red |
| Acute | 12 cubicles | ESI 2–3 | Orange |
| Short-stay Observation | 4 beds | ESI 3 (post-acute) | Yellow |
| Fast-track | 6 chairs | ESI 4–5 | Green |
| Isolation | 1 room | Infectious / unknown | Purple |
| Waiting Room | — | Pre-triage / ESI 4–5 overflow | Grey |

### Roles
| Role | Primary Actions |
|---|---|
| **Registration clerk** | Create visit, capture demographics, insurance |
| **Triage nurse** | ESI assessment, vitals, history, zone assignment |
| **Charge nurse** | Zone oversight, re-triage escalation, shift open/close |
| **ED physician (house officer)** | Assessment, orders, documentation |
| **Registrar / Consultant** | Senior review, complex decisions |
| **EMS crew** | Pre-hospital handover entry |

---

## 2. Data Model Design

### 2.1 `EDVisit` — Core Encounter Record

The anchor model. One per patient visit.

```
Fields:
  patient            → FK emr.Patient (nullable until registered)
  patient_name_unregistered  → Char (used for "John Doe" or EMS nameplates)
  visit_number       → auto-generated (ED-YYYYMMDD-NNN)
  organisation       → FK emr.Organisation

  # 5 timestamps
  arrived_at         → DateTime (auto on create)
  triaged_at         → DateTime (nullable)
  seen_by_doctor_at  → DateTime (nullable)
  disposition_decided_at → DateTime (nullable)
  exited_at          → DateTime (nullable)

  # Arrival
  arrival_mode       → Choice: walk_in, ambulance, wheelchair, police_escort,
                        brought_by_relative, transferred, self_referral
  ambulance_crew     → Char
  referring_facility → Char (if transferred)
  ems_handover_notes → Text

  # Status
  current_status     → Choice: arrived, triaged, in_zone, with_doctor,
                        disposition_pending, discharged, admitted, transferred,
                        absconded, deceased

  # Zone
  current_zone       → Choice: resus, acute, observation, fast_track,
                        isolation, waiting
  current_bed        → Char (e.g. "A3", "Resus-1")
  zone_assigned_at   → DateTime

  # Team
  triage_nurse       → FK User (nullable)
  charge_nurse       → FK User (nullable)
  attending_physician → FK User (nullable)

  # Links
  emr_encounter      → FK emr.Encounter (nullable, set after physician signs)
```

### 2.2 `TriageAssessment` — Triage Nurse's Record

One-to-one with EDVisit. Created when triage nurse submits assessment.

```
Fields:
  visit              → OneToOne EDVisit
  assessed_by        → FK User
  assessed_at        → DateTime

  # Presenting problem
  chief_complaint    → Char(200)
  complaint_onset    → Choice: minutes, hours, days, weeks, months
  complaint_duration → Char (free text, e.g. "2 hours 30 minutes")
  mechanism          → Choice: medical, blunt_trauma, penetrating_trauma,
                        burn, fall, mva, drowning, poisoning, unknown
  trauma_details     → Text

  # ESI
  esi_score          → Integer 1–5
  ai_esi_suggestion  → Integer 1–5 (nullable)
  ai_esi_rationale   → Text
  ai_esi_flags       → JSON list of red-flag strings
  esi_override_reason → Text (if nurse overrides AI suggestion)

  # Vitals
  temp_celsius       → Decimal(4,1)
  bp_systolic        → SmallInt
  bp_diastolic       → SmallInt
  pulse_bpm          → SmallInt
  rr_rpm             → SmallInt
  spo2_percent       → Decimal(4,1)
  weight_kg          → Decimal(5,2)
  pain_score         → SmallInt 0–10
  blood_glucose_mmol → Decimal(4,1)
  gcs_eye            → SmallInt 1–4
  gcs_verbal         → SmallInt 1–5
  gcs_motor          → SmallInt 1–6
  # gcs_total computed property = eye + verbal + motor

  # History
  allergy_nkda       → Boolean (no known drug allergies)
  allergies          → Text
  pmh_htn            → Boolean
  pmh_dm             → Boolean
  pmh_asthma         → Boolean
  pmh_cardiac        → Boolean
  pmh_renal          → Boolean
  pmh_hiv            → Boolean
  pmh_sickle_cell    → Boolean
  pmh_stroke         → Boolean
  pmh_other          → Text
  current_medications → Text
  last_oral_intake   → DateTime (NPO planning)
  pregnant           → Choice: yes, no, unknown, na
  lmp                → Date

  # Nurse notes
  triage_notes       → Text
  re_triage          → Boolean (True if this is a repeat assessment)
  re_triage_reason   → Text
```

### 2.3 `ZoneAssignment` — Zone Movement Log

Every time a patient moves zones, a new record is created. Full audit trail.

```
Fields:
  visit              → FK EDVisit
  zone               → Choice (same set as EDVisit.current_zone)
  bed_number         → Char
  assigned_by        → FK User
  assigned_at        → DateTime (auto)
  ended_at           → DateTime (nullable, set when next assignment created)
  notes              → Text
```

### 2.4 `DispositionRecord`

One-to-one with EDVisit. Created at disposition decision.

```
Fields:
  visit              → OneToOne EDVisit
  decided_by         → FK User
  decided_at         → DateTime

  disposition        → Choice: discharge_home, admit_general_ward,
                        admit_icu, admit_hdu, admit_paeds,
                        transfer_facility, dama, absconded, deceased
  ward_admitted_to   → Char
  transfer_facility  → Char

  discharge_instructions → Text
  follow_up_date     → Date
  follow_up_with     → Char
  prescriptions_issued → Text
  referrals_made     → Text
  disposition_notes  → Text
  cause_of_death     → Text (if deceased)
```

### 2.5 `EDShift`

Open/close shifts for the department. Drives the handover workflow.

```
Fields:
  organisation       → FK emr.Organisation
  shift_type         → Choice: day (07:00–15:00), evening (15:00–23:00),
                        night (23:00–07:00)
  shift_date         → Date
  charge_nurse       → FK User
  opened_by          → FK User
  opened_at          → DateTime
  closed_by          → FK User (nullable)
  closed_at          → DateTime (nullable)
  incoming_notes     → Text (from outgoing team)
  census_at_close    → Integer (patient count when shift ends)
  critical_flags     → Text (charge nurse summary of critical patients)
```

### 2.6 `ShiftHandoverNote` — Per-Patient SBAR

```
Fields:
  outgoing_shift     → FK EDShift
  visit              → FK EDVisit
  situation          → Text
  background         → Text
  assessment         → Text
  recommendation     → Text
  ai_generated       → Boolean
  created_by         → FK User
  created_at         → DateTime
  last_updated_at    → DateTime
```

---

## 3. URL Structure

```
/ed/                         → Redirect → tracking board
/ed/board/                   → Live tracking board (real-time patient whiteboard)
/ed/visits/                  → Today's visit list
/ed/visits/new/              → New arrival registration
/ed/visits/<pk>/             → Visit detail / timeline
/ed/visits/<pk>/triage/      → Triage assessment form
/ed/visits/<pk>/retriage/    → Re-triage form
/ed/visits/<pk>/physician/   → Physician assessment view
/ed/visits/<pk>/disposition/ → Disposition form
/ed/visits/<pk>/zone/        → Quick zone assignment (POST only)
/ed/shifts/                  → Shift management
/ed/shifts/open/             → Open new shift
/ed/shifts/<pk>/handover/    → Shift handover view (SBAR per patient)

# AJAX API
/ed/api/board/               → JSON: live board state
/ed/api/visits/<pk>/esi/     → POST: run AI ESI suggestion
/ed/api/visits/<pk>/zone/    → POST: reassign zone
/ed/api/visits/<pk>/status/  → POST: update status
/ed/api/shifts/<pk>/handover/generate/ → POST: AI-generate SBAR notes
/ed/api/timestamps/<pk>/seen/ → POST: record door-to-doctor timestamp
```

---

## 4. Views & Permissions

### 4.1 Tracking Board (`/ed/board/`)

Live whiteboard showing all active patients grouped by zone.

**Design:**
- One column per zone (Resus → Acute → Observation → Fast-track → Isolation → Waiting)
- Patient cards colored by ESI (red/orange/yellow/green/blue)
- Card shows: patient name/ID, ESI badge, chief complaint, time in dept (auto-refreshing), status badge, assigned doctor
- Auto-refreshes JSON every 30 seconds via polling
- Filter bar: show only ESI 1–2, show only unassigned, show by physician
- Charge nurse can drag-and-drop zones (updates ZoneAssignment via AJAX)
- Critical alerts: flash red if ESI 1 patient waiting > 5 min without being seen

### 4.2 New Visit (`/ed/visits/new/`)

Used by registration clerk or triage nurse on arrival.

**Fields:**
- Patient search (MRN, name, DOB) — links to emr.Patient if found
- If not found: quick capture (name, DOB, sex, phone, address)
- Arrival mode selector
- EMS handover notes (if ambulance)
- Mark as arrived → creates EDVisit, redirects to triage form

### 4.3 Triage Form (`/ed/visits/<pk>/triage/`)

Full triage nurse assessment.

**Sections:**
1. **Presenting Problem** — chief complaint, onset, duration, mechanism
2. **Vital Signs** — temp, BP, HR, RR, SpO2, weight, glucose, pain score, GCS
3. **Red Flag Screen** — AI-assisted (button triggers ESI API, populates suggestion)
4. **ESI Assignment** — nurse selects 1–5, sees AI suggestion, can override with reason
5. **History** — allergies (NKDA checkbox), PMH checkboxes, medications, last meal, pregnancy
6. **Zone Assignment** — auto-suggested by ESI, nurse confirms bed number
7. **Triage Notes** — free text

### 4.4 Physician View (`/ed/visits/<pk>/physician/`)

Shows: patient summary card (demographics + triage sidebar), then full editable encounter.

**Sections:**
- Patient demographics + allergy banner
- Triage summary (read-only): ESI, chief complaint, vitals, PMH
- History of Presenting Illness (editable, AI-assist available)
- Review of Systems (expandable checkboxes)
- Physical Examination (editable)
- Assessment & Plan (editable, ICD-10 search)
- Investigations (ordered/resulted)
- Disposition decision button

### 4.5 Disposition Form (`/ed/visits/<pk>/disposition/`)

Finalizes the visit.

**Fields:**
- Disposition type (discharge, admit, transfer, DAMA, absconded, deceased)
- If admit: ward selection + bed request
- If transfer: facility + reason + clinical summary
- If discharge: instructions + follow-up date + prescriptions
- References to referrals
- Exit time recording

### 4.6 Shift Handover (`/ed/shifts/<pk>/handover/`)

Shows all active patients at shift change.

**Layout:**
- Shift summary at top (census, critical count, pending decisions)
- Per-patient SBAR cards (auto-generated by AI, editable)
- Print/PDF export button
- Sign-off by charge nurse

---

## 5. AI Features

### 5.1 AI ESI Suggestion

**Trigger:** Triage nurse clicks "Get AI Assessment" after entering chief complaint + vitals.

**Input to AI:**
```
Chief complaint: [text]
Vitals: HR [x], BP [x/x], RR [x], Temp [x], SpO2 [x]%, Pain [x]/10
GCS: [x]
Mechanism: [x]
PMH: [list]
```

**Output:**
- ESI 1–5 recommendation
- Rationale (1–2 sentences)
- Red flag list (e.g. "HR > 130 with diaphoresis suggests hemodynamic instability")

**Model:** Uses same Azure OpenAI / OpenAI client as scribe app.

### 5.2 AI Shift Handover SBAR Generation

**Trigger:** Charge nurse opens handover view, clicks "Generate all SBAR notes."

**Per patient, AI generates:**
- **S**ituation: What is the patient here for, current status
- **B**ackground: Relevant PMH, key triage findings
- **A**ssessment: Current clinical picture
- **R**ecommendation: What incoming team needs to do

### 5.3 AI History of Presenting Illness (Physician View)

Takes triage transcript / chief complaint + context, drafts HPI. Doctor edits.

---

## 6. Implementation Order

```
Phase 1 — Foundation (this session)
  [x] Planning document
  [ ] apps/ed/ models (EDVisit, TriageAssessment, ZoneAssignment,
                        DispositionRecord, EDShift, ShiftHandoverNote)
  [ ] apps/ed/ forms
  [ ] apps/ed/ views (all)
  [ ] apps/ed/ URLs
  [ ] apps/ed/ admin
  [ ] AI ESI service (apps/ed/services/ai_esi.py)
  [ ] AI handover service (apps/ed/services/handover.py)
  [ ] Templates: tracking_board, new_visit, triage_form, physician_view,
                  disposition_form, shift_handover, visit_detail, visit_list
  [ ] Update sidebar navigation
  [ ] Register app in settings.py + urls.py
  [ ] makemigrations + migrate

Phase 2 — Enhancement (future session)
  [ ] Drag-and-drop zone reassignment on tracking board
  [ ] WebSocket real-time updates (replace polling)
  [ ] Printed triage sticker (label-format PDF)
  [ ] SMS/WhatsApp notification to patient on disposition
  [ ] GNU Health Encounter auto-push on physician sign
  [ ] Nurse-to-doctor async messaging per visit
  [ ] QR wristband generation on registration
  [ ] ED dashboard analytics (LOS averages, ESI distribution, re-triage rate)
  [ ] Paeds weight-based drug dosing calculator in physician view
  [ ] PACS / radiology order integration
```

---

## 7. Constants Reference

### ESI Decision Tree (condensed)
```
ESI 1 → Requires immediate life-saving intervention
  → Intubation, defibrillation, emergent surgery
  → Airway compromise, pulseless, unresponsive

ESI 2 → High-risk situation OR severe pain/distress
  → Altered mental status, severe pain (8–10/10)
  → New hemiplegia, acute MI presentation, sepsis

ESI 3 → How many resources? Two or more
  → Stable vitals, will need labs + imaging + IV fluids
  → Most abdominal pain, moderate injuries, respiratory illness

ESI 4 → One resource needed
  → Simple laceration needing sutures, UTI, mild sprain

ESI 5 → No resources needed
  → Medication refill, minor rash, suture removal
```

### Vital Sign Danger Thresholds (auto-flagged)
```
HR > 130 or < 40
SBP < 90 or > 220
RR > 30 or < 8
SpO2 < 90%
Temp > 39.5°C or < 35°C
GCS < 14
Pain > 8/10
```

### Disposition Codes
```
DH   = Discharge home
AW   = Admit — general ward
AI   = Admit — ICU
AH   = Admit — HDU
AP   = Admit — paediatric ward
TR   = Transfer to another facility
DA   = Discharged against medical advice (DAMA)
AB   = Absconded
DC   = Deceased (in department)
```

---

## 8. Caribbean-Specific Considerations

- **Common presentations:** hypertensive emergency, diabetic emergency (DKA/HHS), dengue fever, leptospirosis, trauma (MVA, assault), sickle cell crisis, asthma exacerbation, gastroenteritis
- **Drug names:** Jamaican brand names (Panadol, Vita-Cax, Calchek) alongside generics
- **Insurance:** NHF card, private insurer, self-pay — captured at registration
- **Language:** Patois spoken by many patients; triage notes may include Patois transcription from ASR
- **EMS:** Ministry of Health ambulances + private EMS — different handover formats
- **Reporting:** MoH weekly ED census reports require disposition codes, LOS data, chief complaint categories
