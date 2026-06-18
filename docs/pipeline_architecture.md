# WellNest Scribe — Pipeline Architecture

## Ambient Scribe Pipeline

### Current state (as of June 2026)

```
Audio → OmniASR (target_lang) → raw_transcript → Patois interpreter → SOAP generator
                                                   (Jamaica-specific)   (Jamaica context)
```

All three stages are hardcoded for Jamaica regardless of `DoctorProfile.preferred_language`.
The language field reaches the ASR model but nothing downstream.

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

### Implementation change points (not yet done)

1. `apps/scribe/services/pipeline.py` — pass `preferred_language` into the pipeline entry point;
   add a routing check before `run_interpret_patois()`.

2. `apps/scribe/services/soap_generator.py` — make `JAMAICAN_CONTEXT_ADDENDUM` conditional on
   `lang == "jam_Latn"`; add a `GENERIC_CONTEXT_ADDENDUM` for other languages.

3. `apps/scribe/services/triage.py` — write `run_interpret_generalized()` using a stripped-down
   version of the Patois interpreter prompt with Jamaica-specific sections removed.

4. `apps/scribe/views.py` — `ambient_transcribe_api` already reads `preferred_language` from the
   doctor profile for ASR; extend this to pass it into the note generation call.

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
| eng_Latn  | English           | OmniASR    | None (skip)     | Generic          | ASR only     |
| spa_Latn  | Spanish           | OmniASR    | None (skip)     | Generic          | ASR only     |
| fra_Latn  | French            | OmniASR    | None (skip)     | Generic          | ASR only     |
| hat_Latn  | Haitian Creole    | OmniASR    | Generalized     | Generic          | ASR only     |
| por_Latn  | Portuguese        | OmniASR    | None (skip)     | Generic          | ASR only     |

"ASR only" = transcription works, but note generation still uses Jamaica context until the
three-tier pipeline is implemented.

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

*Last updated: June 2026. Update this file when pipeline tiers are implemented.*
