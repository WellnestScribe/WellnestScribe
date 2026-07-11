# WellNest — Multi-specialty + Document/OCR Architecture (planning, not built)

> **Status: DESIGN ONLY. Do not build yet.** This walks through how to support other
> office types (dentist, radiologist, lab) and add image/document upload + historical-record
> OCR **cost-effectively**, without a document database and without breaking the GP workflow.

---

## 1. Multi-specialty (dentist, radiologist, lab, pharmacy) — config, not a fork

**Key insight: the workflow is already generic.** Register patient → find patient → appointment →
encounter → note works for *any* office. What actually differs by specialty is only:
- **Templates & labels** (a dentist's note ≠ a GP SOAP note; a radiologist writes a "Report").
- **What they capture** (radiologist reads an image + reports; lab records results; dentist charts teeth).

**Do NOT fork the workflow or bury the admin in dropdowns.** Drive everything off data we already have:
- `DoctorProfile.role` already exists (doctor / nurse / **radiologist** / **pharmacist** / **lab_tech**)
  and `DoctorProfile.specialty`. The system already knows who the user is.
- Add **ONE optional field** to `Organisation`: `clinic_type` (general / dental / radiology / lab /
  pharmacy / multi). That single setting picks sensible defaults for the whole facility. **One
  dropdown, set once at onboarding — not many.**

What the config changes (all data/labels, **no schema change to Patient/Encounter/Appointment**):
- **Note templates** — extend the existing template system (we already have SOAP / narrative / chart +
  quick templates for HTN, diabetes, antenatal…). Add: dental exam, radiology report, lab result.
  These are prompt/template data, not new code paths.
- **Labels** — e.g. show "Report" instead of "SOAP" for radiology; "Findings" section for imaging.
- **Encounter type choices** — already a simple choices list; add a few (dental, imaging, lab) if wanted.

**Net:** the GP flow is untouched. A dental clinic just gets dental defaults. Cost to build ≈ **$0
infra** (one org field + a few templates). Radiologist/lab specifically *consume the document feature*
below (view the uploaded image, write the report / record the result).

Principle: **configuration over duplication.** The pipeline is universal; specialty only swaps
templates + labels, which are config.

---

## 2. Image / document upload — cost-effective, NO document database

**Your instinct is right: don't add a document database (Mongo etc.).** The correct, cheap pattern:

> **Files → object storage (Azure Blob). Metadata → the existing MySQL DB. Never store bytes in SQL.**

### The pieces
- **Object storage: Azure Blob** (you're already on Azure). Cost is trivial:
  - Hot tier ≈ **$0.018 / GB / month**. A compressed photo of a lab result ≈ 200–800 KB.
  - **10,000 images ≈ 5 GB ≈ ~$0.10 / month.** 100 GB ≈ ~$1.84 / month. **Storage is a non-issue.**
- **Metadata: one normal SQL table** — a lightweight `Document` model (NOT a document DB):
  ```
  Document(organisation FK, patient FK, uploaded_by, doc_type[lab|imaging|referral|note|other],
           title, captured_date, blob_key, mime, size_bytes, created_at)
  ```
  Tiny rows, pennies. Same DB, same multi-tenant `organisation` scoping as everything else.
- **Upload path (cheap on bandwidth):**
  1. Doctor taps "Add document" → phone camera / file input.
  2. **Compress client-side** (canvas resize + JPEG ~0.7 quality → ~200–500 KB). Big saving before a byte leaves the phone.
  3. **Direct-to-blob** via a short-lived **SAS upload URL** minted by Django → the file goes phone→Blob
     directly, *never through the app server* (saves server bandwidth/CPU). Then POST the metadata row.
  4. (Simpler v1: stream through Django to Blob. Fine at low volume; move to direct SAS later.)
- **View path:** when a doctor opens a document, Django mints a **time-limited SAS read URL**; the
  browser loads the image straight from Blob. Nothing is cached in the app or the DB.

### Security / compliance
- Private Blob container; access only via **short-lived, per-request SAS URLs** (no public URLs).
- Org-scoped metadata; audit-logged; Blob encryption-at-rest is on by default in Azure.
- Never save the raw file to the phone gallery (stream + discard), matching the existing scribe policy.

### Cost summary
Storage pennies/month + tiny SQL rows. **The only real cost is bandwidth, minimized by
client-side compression + direct-to-blob.** No document DB, no new database engine.

---

## 3. Historical physical records → OCR — on-demand & additive, never bulk

Goal: get old paper dockets into the system for reference, cheaply and safely.

### Hard rules (safety + cost)
- **Do NOT bulk-OCR the backlog.** It's expensive *and* dangerous — handwriting OCR errs, and a misread
  "5mg" → "50mg" is a patient-safety event. **The image is the source of truth; OCR is additive.**
- **Scan-on-demand, not a mass project.** First time a patient visits after go-live, capture their
  docket once → digital forever. Patients who never return never get scanned. The cabinet digitizes
  itself over 6–12 months, and only the part that's actually used. A **"mark as scanned" flag** makes it
  self-terminating.
- **Tool is the phone**, not a $150 scanner — in-app batch camera capture (auto-crop, compress, stream
  to Blob). ~30–60 sec for a 15-page docket. On-device blur check (Laplacian variance) rejects bad
  photos *before* upload — don't spend AI just to ask "is this blurry?".

### Three levels (safest first) — pick how far up you go
- **Level 1 — capture-time tags (do this; NO AI):** the person scanning picks a **doc type + date**
  (one dropdown + a date). The archive becomes searchable/sortable while the image stays untouched.
  Baseline that makes the archive usable at all. **Cost: $0 AI.**
- **Level 2 — light AI indexing (later; low risk):** a **cheap vision model** (Gemini Flash or
  GPT-4o-mini vision) classifies the type, reads the date, suggests a title; a human confirms in one
  tap. The AI produces the **index, not the record** — a mis-tag means "filed wrong," not "wrong dose."
  **Cost: ~60 output tokens/image → ~$7–14 to index 10,000 images on a mini model, ~halved with the
  Batch API.** Cheap because a tag is tiny, not a whole page.
- **Level 3 — full content OCR (defer / avoid):** extracting values/meds/doses into fields the doctor
  relies on. This is the risky one. Keep it **off**, or strictly **on-demand and labelled**
  "AI-extracted — verify against original." Only when a doctor explicitly opens a page and asks.

### Model choice
Use a **cheap vision model (Gemini Flash / GPT-4o-mini)** for Level-2 classification/date-reading.
Reserve any frontier model for rare on-demand content extraction. This keeps OCR cost near-zero.

### Cost summary
Storage pennies; Level-1 tagging free; optional Level-2 indexing ~$7–14 one-time for a whole cabinet.
The real cost is **human capture time**, which scan-on-demand spreads out instead of paying up front.

---

## 4. Why this is affordable (the whole point)
The ONE cost that scales with usage is **AI (omniASR GPU + GPT-5.4 tokens)** — everything here avoids
adding to it:
- Multi-specialty = config, **$0 infra**.
- Documents = Blob storage (**pennies**) + tiny SQL metadata rows, **no document DB**.
- OCR = **on-demand + additive**, cheap mini-model for indexing only, never bulk, never the record.

Infra stays a shared, largely-fixed cost (single multi-tenant DB + one Blob container), so per-clinic
cost keeps falling as you grow. Documents/OCR add **cents**, not a new cost centre.

---

## 5. How this connects to the incubator feedback (June 30, 2026)
- **"Never cut a doctor off mid-consult"** → already our design: audio-minute metering, per-session
  auto-stop + silence auto-stop, **soft-cap at 100% (never block)**, warn at 80%. Jesse's "rollover"
  tension is handled by billing on audio-minutes, not hard note counts.
- **Moat = local (Patois/Jamaican-English accuracy, local compliance/residency)** → lead with this; the
  document/OCR + local records + data residency deepen the moat global scribes won't prioritize.
- **Volume/group pricing** → institutions already get per-seat pricing (min 10, 20% off 5+).
- **"Note" definition / varying consult length** → we moved off note caps to **audio-hours** so a
  5-min vs 45-min consult is priced fairly.
- **Paid pilot > verbal yes; bottom-up via private practices + referral loop; compliance early** →
  go-to-market notes to carry into the plan (not an engineering task).

## 6. If/when we build (suggested order, later)
1. `Document` model + Azure Blob container + phone capture (compress → stream/SAS) + view via SAS.
2. Level-1 capture-time tags + "mark as scanned" flag + Patient → Documents timeline.
3. `Organisation.clinic_type` + specialty note templates (dental / radiology / lab).
4. Level-2 AI indexing (cheap vision model, human-confirm) — only after 1–2 are in use.
5. Level-3 on-demand content OCR — only if clearly demanded, always labelled + verify-against-original.
