# WellNest Scribe — Pipeline Architecture

## Ambient Scribe Pipeline

### Current state (as of June 2026) — v3 implemented

```
Audio → OmniASR (target_lang) → raw_transcript → run_interpret_for_lang() → SOAP generator
                                                   (language-tier routed)   (lang-aware context)
```

All three stages now respect `DoctorProfile.preferred_language`. The three-tier routing
is live for both the two-call path (`generate_note_api`) and the streaming path
(`generate_note_stream_api`).

---

### Planned architecture — multi-language ambient pipeline

Three tiers based on `DoctorProfile.preferred_language`:

```
jam_Latn (Jamaican Creole)
  → OmniASR → Patois interpreter (existing, unchanged) → SOAP + Jamaica context addendum

hat_Latn (Haitian Creole) — "low-resource" tier
  → OmniASR → Generalized interpreter (strips Jamaica-specific logic, keeps raw-speech→clinical structure) → SOAP + generic clinical context

eng_Latn / spa_Latn / fra_Latn / por_Latn — "high-resource" tier
  → OmniASR → skip interpreter (GPT handles natively) → SOAP + generic clinical context
```

**Low-resource definition:** Languages where GPT-4 class models lack enough medical training data
to reliably interpret raw clinical speech without a priming step. Currently: Haitian Creole (hat_Latn).
Add others as needed when expanding to new regions.

**High-resource definition:** Languages with strong GPT-4 native support — English, Spanish,
French, Portuguese. No interpretation step needed; transcript goes directly to note generation.

---

### Implementation change points — DONE (v3)

1. **`apps/scribe/services/pipeline.py`** — `_lang_tier()` helper; `run_interpret_for_lang()`
   routes to `run_interpret_patois` / `run_interpret_generalized` / pass-through;
   `run_note_generation()`, `run_stream_note_generation()` accept `lang=` and forward it.

2. **`apps/scribe/services/soap_generator.py`** — `_system_prompt()` accepts `lang=`;
   uses `JAMAICAN_CONTEXT_ADDENDUM` for `jam_Latn`, `GENERIC_CONTEXT_ADDENDUM` for all others;
   `generate_note()`, `generate_modular_soap()`, `stream_note_generation()` all thread `lang=` through;
   `interpret_generalized()` / `_GENERALIZED_INTERPRETER_PROMPT` added for low-resource tier.

3. **`apps/scribe/views.py`** — both `generate_note_api` and `generate_note_stream_api` read
   `profile.preferred_language` into `_lang`, pass it to `run_interpret_for_lang()` and note
   generation calls.

---

### Dictation mode — separate TODO

Dictation will use **GPT-4o Transcribe / Whisper** (OpenAI direct), not OmniASR.
Whisper has auto-detect so the language selection is mostly irrelevant for dictation transcription.
Note generation side can reuse the same three-tier routing above when that feature is built out.
Do NOT add language routing to dictation until the GPT-4o Transcribe integration is done.

---

### Language support matrix

| Code      | Language          | ASR model  | Interpreter     | Note context     | Status       |
|-----------|-------------------|------------|-----------------|------------------|--------------|
| jam_Latn  | Jamaican Creole   | OmniASR    | Patois pipeline | Jamaica addendum | Live         |
| eng_Latn  | English           | OmniASR    | None (skip)     | Generic          | Live (v3)    |
| spa_Latn  | Spanish           | OmniASR    | None (skip)     | Generic          | Live (v3)    |
| fra_Latn  | French            | OmniASR    | None (skip)     | Generic          | Live (v3)    |
| hat_Latn  | Haitian Creole    | OmniASR    | Generalized     | Generic          | Live (v3)    |
| por_Latn  | Portuguese        | OmniASR    | None (skip)     | Generic          | Live (v3)    |

---

### OmniASR language list expansion

The MMS model (Facebook/Meta) supports 1,100+ languages via the `lang_ids` registry.
The current 6-language picker in the UI is a placeholder. When expanding:
- Add a searchable language dropdown (the full MMS language list is available at runtime
  via `omnilingual_asr.models.wav2vec2_llama.lang_ids.supported_langs`)
- Classify each new language as high-resource or low-resource for the pipeline tier decision
- A language can be added to the UI before its note-generation tier is ready — just show a
  banner that note quality may vary for that language

---

*Last updated: June 2026. v3 three-tier pipeline implemented.*
