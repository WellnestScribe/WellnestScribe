# WellNest Scribe — Note Generation Pipeline

> **Purpose of this document**: Snapshot of how the ambient recording → SOAP note pipeline works
> *before* any combined-call or streaming optimisations. If you are reimplementing or optimising
> this pipeline, read this first so you understand what every piece does and why.

---

## 1. End-to-End Flow (Ambient Mode)

```
Doctor presses Record
      │
      ▼
[Browser] MediaRecorder captures audio → WebM blob
      │
      ▼ POST /scribe/api/sessions/<pk>/upload-audio/   (creates ScribeSession row)
      │
      ▼ POST /scribe/api/sessions/<pk>/ambient-transcribe/
      │         body: { backend: "modal-omni" }
      │
      ▼ [Django] ambient_transcribe_api  →  submit_triage_job(_run)
      │         spawns background thread
      │
      ▼ [Django returns immediately]  { ok: true, job_id: "asr-ambient-modal-omni-<uuid>" }
      │
      ▼ [Browser] polls  GET /scribe/api/ambient-jobs/<job_id>/   every 2 s
      │
      │   [Background thread]
      │       transcribe_modal_omni(audio_path)
      │         → POST to Modal GPU (turbogary555 endpoint)
      │         → returns { transcript, audio_seconds, inference_ms, ... }
      │       ScribeSession.objects.filter(pk=pk).update(raw_transcript=raw_text)
      │       job.stage = "done"
      │
      ▼ [Browser] poll sees status=="done", gets transcript from job.result.raw_text
      │
      ▼ POST /scribe/api/sessions/<pk>/generate/
      │         body: { transcript: "<raw ASR text>", note_format, length_mode, ... }
      │
      ▼ [Django] generate_note_api   ← THIS IS THE SLOW PART (two GPT-5 calls)
      │
      ▼ [Django] redirects browser to  /scribe/sessions/<pk>/review/
```

---

## 2. The Two GPT-5 Calls in `generate_note_api`

`generate_note_api` is in `apps/scribe/views.py`. It always runs **two sequential Azure OpenAI calls**
against the `gpt-5-chat` deployment. This is the current performance bottleneck.

### Call 1 — Patois Interpreter  (~10–15 s)

```
run_interpret_patois(raw_source)
    ↓
soap_generator.interpret_patois(patois_text)
    ↓
_preprocess_patois(text)         # deterministic regex rewrites (no LLM cost)
    ↓
_chat([system, user])            # GPT-5 call
```

**What `_preprocess_patois` does (zero LLM cost, runs in microseconds):**
- Wraps numerical self-corrections: `"siks nou iz ant iz a iet"` → `[SELF-CORRECTION: ... Active value is 8]`
- Tags `kyaan/kaan` variants → `[CANNOT: ...]`
- Tags `woulda/wuda` → `[CONDITIONAL-not-definite: ...]`
- Strips discourse markers
- Annotates BP verbal patterns: `"120 ova 80"` → `[BLOOD PRESSURE READING: 120 over 80 — verify]`
- Annotates approximations: `"bout 5"` → `[APPROXIMATE VALUE ~5 — do not record as exact]`

**What GPT-5 is asked to do (the `PATOIS_INTERPRETER_SYSTEM_PROMPT` in `soap_generator.py`):**

The prompt is ~400 lines / ~5 000 tokens. It instructs the model to work in 3 explicit steps:

| Step | What it does | Why |
|------|-------------|-----|
| STEP 1 — PHONETIC RESOLUTION | Token-by-token mapping of every Patwa word to English (e.g. `mi=I`, `beli=abdomen`) | Chain-of-thought for non-reasoning models |
| STEP 2 — ASSEMBLED ENGLISH | Converts resolved tokens into grammatical clinical English sentences | **This is the only output actually used downstream** |
| STEP 3 — CLINICAL INTERPRETATION | Structured summary: Chief Complaint, Location, Onset, Severity, etc. | Not used by SOAP generator; kept for audit trail |

**Critical rules embedded in the prompt:**
- Negation safety: `kyaahn/cyaahn = CANNOT`, `nuh/nah = NO`, `neva = NEVER`
- Self-correction disambiguation: `"nou"` = correction (discard old value) vs temporal "now"
- Patient minimising: `"likkle likkle"` before a symptom = downplaying, flag it
- Patois numerals → Arabic digits before any dose / pain score
- Herb tagging: `[HERBAL SUPPLEMENT]` on 20+ named Jamaican herbs
- Anatomical disambiguation: `"batam op mi fut"` = plantar foot, NEVER abdomen

**Output extraction (`_extract_step2` in views.py):**
```python
def _extract_step2(stored: str) -> str:
    m = re.search(
        r"STEP\s+2[^:]*:\s*\n+(.*?)(?=\n---|\nSTEP\s+3\b|\Z)",
        stored, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""
```
Only Step 2 content is kept. Step 1 (~500–1 000 output tokens) and Step 3 are immediately discarded.

---

### Call 2 — SOAP Note Generator  (~10–20 s)

```
run_note_generation(transcript=step2, note_format, specialty, length_mode, ...)
    ↓
soap_generator.generate_note(transcript, ...)
    ↓
_system_prompt(specialty, custom_instructions, ...)
    ↓
_chat([system, user])            # GPT-5 call
```

**System prompt layers (assembled by `_system_prompt()` in `soap_generator.py`):**
1. `MASTER_SYSTEM_PROMPT` (~100 lines) — core extraction rules, SOAP format, output style
2. `JAMAICAN_CONTEXT_ADDENDUM` (~60 lines) — common JA meds, herbal remedies, Patois translations
3. `specialty_addendum(specialty)` — specialty-specific rules if not general (from `prompts.py`)
4. `SENSITIVE_ENCOUNTER_ADDENDUM` — PHI minimisation rules (when `session.is_sensitive=True`)
5. `SUGGESTIVE_ASSIST_ADDENDUM` — enables suggestive "consider / rule out" phrasing (optional)
6. Doctor's custom terms and custom instructions (from `ScribeProfile`)

**User prompt (`SINGLE_SOAP_USER_PROMPT` in `prompts.py`):**
Instructs the model to produce exactly these sections in order:
```
SUMMARY:    (2–3 bullet TL;DR)
S:          (CC, HPI, PMH, Family, Social, Meds, Allergies, ROS)
O:          (Vitals, Examination, Investigations)
A:          (numbered differential / impression)
P:          (numbered plan items)
AI-generated draft - review and edit required before clinical use.
```

**Retry logic for empty output (`_chat()` in `soap_generator.py`):**
GPT-5 is a reasoning model. If its token budget is consumed by internal reasoning, the visible
output can be empty. The `_chat()` function handles this:
- Attempt 1: `max_completion_tokens=4000`, `reasoning_effort="minimal"`
- Attempt 2 (if output empty): `max_completion_tokens=8000`, `reasoning_effort="low"`
- If still empty → raises `RuntimeError` → `generate_note_api` returns HTTP 502

**Refusal-pattern retry (`generate_note()`):**
If SOAP came back with 3+ sections as `"Not documented"` but the transcript has content,
the model was too conservative. The function re-prompts with a stricter extraction nudge
and the previous "refusal" response, asking the model to try again.

---

## 3. Session State Machine

```
ScribeSession.status:

  "pending"    → just created, no audio yet
  "uploaded"   → audio file attached, waiting for transcription
  "transcribed" → raw transcript saved (ambient flow: never set explicitly,
                  goes straight to "generating" when generate is called)
  "generating" → generate_note_api running (set before GPT-5 calls)
  "review"     → note generated; doctor on review page
  "error"      → something failed; error_message field set
```

**Key `ScribeSession` fields:**

| Field | Content |
|-------|---------|
| `raw_transcript` | Raw ASR output (Patwa phonetic text) from Modal GPU. Set by `ambient_transcribe_api._run()` and cached by `generate_note_api` from POST body. |
| `transcript` | Clean Step 2 clinical English. Set by `generate_note_api` after `interpret_patois`. Reused on regeneration — no second interpret call. |
| `note_format` | `"soap"` / `"narrative"` / `"chart"` |
| `length_mode` | `"brief"` / `"normal"` / `"detailed"` |
| `is_sensitive` | Boolean — triggers `SENSITIVE_ENCOUNTER_ADDENDUM` |
| `patient_gender` | `"M"` / `"F"` / `"O"` — prepended to custom instructions so AI uses correct pronouns |

**Regeneration logic (second call to generate for same session):**
- `is_first_generation = not SOAPNote.objects.filter(session=session).exists()` 
- If `is_first_generation=False` AND `force_reinterpret=False`: skips `interpret_patois`, uses cached `session.transcript` directly
- If `force_reinterpret=True`: re-runs interpret even on regeneration

---

## 4. File Map

```
apps/scribe/
├── views.py
│   ├── generate_note_api          ← orchestrates the two GPT-5 calls
│   ├── ambient_transcribe_api     ← starts background transcription job
│   └── ambient_job_api            ← poll endpoint for transcription status
│
├── services/
│   ├── soap_generator.py          ← ALL LLM logic lives here
│   │   ├── _preprocess_patois()   ← deterministic regex (free)
│   │   ├── interpret_patois()     ← GPT-5 call 1: Patois → Step1/2/3 block
│   │   ├── generate_note()        ← GPT-5 call 2: clinical English → SOAP
│   │   ├── generate_modular_soap()← modular mode: 4 separate SOAP section calls (unused)
│   │   ├── _chat()                ← shared chat function with retry logic
│   │   └── validate_note_safety() ← deterministic safety checks (free)
│   │
│   ├── pipeline.py                ← stub-aware wrappers (use_real_ai gate)
│   │   ├── run_interpret_patois() ← wraps interpret_patois with stub fallback
│   │   └── run_note_generation()  ← wraps generate_note with stub fallback
│   │
│   ├── prompts.py                 ← SOAP prompt strings only (no LLM logic)
│   │   ├── MASTER_SYSTEM_PROMPT
│   │   ├── SINGLE_SOAP_USER_PROMPT
│   │   ├── JAMAICAN_CONTEXT_ADDENDUM
│   │   └── ... (other prompts)
│   │
│   ├── clients.py                 ← AzureOpenAI client factory (lru_cache)
│   │   └── get_chat_client()      ← returns AzureOpenAI(key, endpoint, api_version)
│   │
│   └── triage.py                  ← Modal GPU helpers
│       └── transcribe_modal_omni() ← HTTP POST to friend's Modal endpoint
│
├── models.py
│   ├── ScribeSession              ← one row per doctor-patient encounter
│   └── SOAPNote                  ← generated note fields (one per session)
│
└── urls.py                        ← route definitions

templates/scribe/record.html       ← all frontend JS lives here
                                     runAmbientPipeline() orchestrates the flow
```

---

## 5. Key Settings (`.env` / `settings.py`)

| Setting | Value | Effect |
|---------|-------|--------|
| `SCRIBE_AZURE_OPENAI_DEPLOYMENT` | `gpt-5-chat` | Model used for BOTH interpret and SOAP calls |
| `SCRIBE_AZURE_OPENAI_ENDPOINT` | `https://garybryan2021-0878-...cognitiveservices.azure.com/` | Azure resource |
| `SCRIBE_AZURE_OPENAI_API_VERSION` | `2024-12-01-preview` | API version |
| `SCRIBE_MAX_COMPLETION_TOKENS` | `4000` (env) → bumped to `4000` min for reasoning models | Output token budget per call |
| `SCRIBE_PIPELINE_MODE` | `single` | `single` uses `generate_note()` (one SOAP call); `modular` uses `generate_modular_soap()` (4 separate calls — slower, not recommended) |
| `SCRIBE_USE_REAL_AI` | `True` | Enables real Azure OpenAI; `False` returns stub data |
| `SCRIBE_VERIFIER_ENABLED` | `False` | Off; would add a third LLM call for fact-verification |
| `AMBIENT_BACKEND` | `modal-omni` | Default transcription backend |
| `MODAL_OMNI_URL` | `https://turbogary555--...modal.run/transcribe/omni/file` | Friend's Modal GPU endpoint |
| `MODAL_OMNI_API_KEY` | `ak-DF0UQZxW6uhL3bs3XFzti0` | Auth key for Modal endpoint |

---

## 6. Why GPT-5 Cannot Be Replaced for Interpret

Previous attempts with `gpt-5-nano` and `gpt-4o` produced unacceptable results on the Patois
interpretation step. GPT-5's reasoning model architecture is required because:

1. **Negation disambiguation is safety-critical**: `"mi nuh have pain"` (no pain) vs `"mi have pain"` (has pain).
   Weaker models flip negations under load.
2. **Self-correction tracking**: `"pain iz siks nou iz ant iz a iet"` — the patient corrected 6→8.
   The correction signal `"nou iz ant iz"` is a speech restart, not "now". This requires reasoning.
3. **Patois phonetics are non-standard**: `"naip mi"` = stabbing pain (not "knife me").
   `"batam op mi fut"` = plantar foot pain (not abdominal). Weaker models hallucinate anatomy.
4. **Clinical minimising patterns**: `"a nuh nutten... bot di pien bad bad bad"` — patient says
   "it's nothing" then admits severe pain. A non-reasoning model will document "no pain."

The verbose Step 1/Step 2/Step 3 structure was designed to force chain-of-thought in non-reasoning
models. GPT-5 can do this internally via reasoning tokens, which is the basis for Optimisation 1 below.

---

## 7. Optimisations (implemented post this snapshot)

### Optimisation 1 — Slim Interpret Output
**File**: `apps/scribe/services/soap_generator.py` → `interpret_patois()`  
**Change**: Append instruction to the `combined` prompt telling GPT-5 to skip writing STEP 1
and STEP 3 in its visible output (do them as internal reasoning). Only output STEP 2.  
**Saving**: ~500–1 000 fewer visible output tokens per call → ~5–8 s saved on interpret call.  
**Risk**: Low. The regex `_extract_step2()` has `\Z` fallback so works even without STEP 3 as delimiter.

### Optimisation 2 — Combined Single Call
**Files**: `soap_generator.py` + `views.py`  
**Change**: New function `interpret_and_generate_soap()` that appends SOAP generation rules after
the Patois interpreter template and asks the model to output BOTH the clinical English summary
AND the SOAP note in one response, separated by `---SOAP---`.  
**Saving**: Eliminates one entire GPT-5 round-trip → ~10–15 s saved.  
**Controlled by**: `SCRIBE_COMBINED_PIPELINE=True` in `.env`.  
**Risk**: Medium. Input prompt is larger (~8 000 tokens); more complex output parsing.

### Optimisation 3 — Streaming SOAP Generation
**Files**: `soap_generator.py` + `views.py` + `urls.py` + `record.html`  
**Change**: New endpoint `/scribe/api/sessions/<pk>/generate/stream/` that uses OpenAI's `stream=True`
to yield SSE events as the SOAP note tokens arrive. The interpret step still blocks (no streaming
possible), but the SOAP text appears on screen word-by-word starting at ~3 s after generation begins.  
**Saving**: Total wall time unchanged, but *perceived* latency drops from "wait 20 s then see everything"
to "text starts appearing at 3 s."  
**Risk**: Medium. Django `StreamingHttpResponse` + WSGI requires careful buffering config. Nginx/gunicorn
must have `X-Accel-Buffering: no` set or text will batch-flush.
