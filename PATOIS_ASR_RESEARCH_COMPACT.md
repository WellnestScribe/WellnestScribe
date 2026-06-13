# WellNest Scribe — Patois ASR Research Prompt (Compact Edition)
*Paste Part A as system prompt, then Part B as user turn. ~20,000 chars total.*

---

## PART A — SYSTEM CONTEXT (paste as system prompt)

**WellNest Scribe** is a clinical AI scribe for Jamaican primary care and emergency medicine.
Users: nurses transcribing Patois-speaking patients; GPs dictating in Jamaican English.
Deployed on Django 5 / Azure App Service.

### Pipeline — MODE 1: Nurse Triage (Patois → SOAP)
```
AUDIO
 ↓ Step 1 — facebook/mms-1b-l1107 (Wav2Vec2 CTC, 1.1B params, "jam" adapter)
   • Resampled 16kHz mono (PyAV + librosa)
   • 25-second fixed chunks; greedy decode: torch.argmax(logits, dim=-1)
   • Output: raw Patois phoneme string e.g. "mi belly a hurt mi bad since mawnin"
 ↓ Step 2 — Qwen3-1.7B (local CPU/CUDA)
   • Prompt: "Jamaican Patois-to-clinical-English medical interpreter"
   • Tags herbs as [HERBAL SUPPLEMENT], unclear audio as [unclear: "..."]
   • Output: neutral clinical English, third person
 ↓ Step 3 — GPT-5 (Azure OpenAI)
   • EXTRACT, DON'T INVENT system prompt
   • Jamaican context addendum: ~40 drug names, 8 herb-interaction flags,
     8 Patois→clinical mappings, 8 critical alert categories
   • Output: SUMMARY + S + O + A + P sections
```

### Pipeline — MODE 2: Doctor Dictation (English → SOAP)
```
AUDIO → GPT-4o-transcribe (Azure, primed with Jamaican medical vocabulary)
      → GPT-5 SOAP generation (same as Mode 1 Step 3)
```

### Implemented Safeguards
- "EXTRACT DON'T INVENT" — missing values → `[value not stated]` / `[dose not stated]`
- 8 critical alerts: sepsis, FAST stroke, SpO2<92%, severe HTN, hypoglycaemia, neonatal fever, SI, anaphylaxis
- 8 herb-drug flags: cerasee+Metformin, bissy, fever grass, soursop leaf, jackass bitters
- Verifier prompt flags `[HALLUCINATION]` / `[OMISSION]` — disabled by default
- AI disclaimer at note end · JDPA 2020 PHI minimisation mode

### Known Technical Constraints
- CTC greedy decode: torch.argmax — no beam search, no LM rescoring
- No diarization: nurse + patient + family merged in one channel
- Naive stitching: " ".join(chunks) — no overlap, no cross-chunk context
- No audio preprocessing: no VAD, noise reduction, or normalisation
- No CTC confidence scores surfaced to downstream stages
- MMS "jam" adapter: general Jamaican audio, not medical domain
- Qwen3-1.7B: limited context window, hallucination-prone on ambiguous input
- GPT-5 sees text only — no timestamps, no turn structure

### NOT Currently Implemented
No diarization · No numeric/dose NER · No CTC confidence surfacing · No audio SNR gate ·
No structured IR before SOAP · No production hallucination metric · No streaming ASR ·
No session-level patient history in prompt · No medication reconciliation

### Patois Lookup Table in SOAP Prompt (static, 8 entries only)
"mi belly a hurt mi"→abdominal pain · "mi cyaan breathe good"→dyspnoea ·
"mi head a hurt mi bad"→severe headache · "mi pressure high"→elevated BP ·
"mi sugar high"→elevated glucose · "mi feel fi vomit"→nausea/vomiting ·
"mi belly a run"→diarrhoea · "di pickney have fever"→paediatric fever

---

## PART B — RESEARCH PROMPT (paste as user turn)

```
RESEARCH TASK: Failure Mode Analysis & Improvement Roadmap — WellNest Scribe Patois ASR Pipeline

You are an expert in CTC/seq2seq ASR, clinical NLP, Jamaican Creole linguistics, AI safety,
and low-resource dialect adaptation. Using the context above, provide a rigorous clinically-
grounded analysis of every failure mode affecting patient safety, note accuracy, or workflow.
Give concrete improvement strategies within: 3-person team, $500/month cloud, no large
labelled Jamaican medical audio corpus.

══════════════════════════════════════════════════════════
SECTION 1 — NUMERICAL AND QUANTITATIVE MISINTERPRETATION
══════════════════════════════════════════════════════════
1.1 Pain scale hallucination
    "Mi pain like a five out of ten" — MMS may mangle "five"; GPT-5 may write 8/10.
    → Mechanisms at acoustic, linguistic, and LLM level?
    → Validation strategy to prevent silent numeric change?
    → Should system refuse to generate a pain score if no numeral in transcript?

1.2 Vital sign hallucination
    "Pressure was a bit high" → GPT-5 writes "BP 150/90" (fabricated).
    → How do DAX/Freed/DeepScribe handle this?
    → Prompt engineering, output validation, or JSON schema to prevent fabricated vitals?

1.3 Dosage and frequency transcription
    Patois: "wan tablet" (one tablet), "BD" → "be-dee", "take to tablets" (homophone).
    → Robust numeral/dose extraction from Creole ASR output?
    → Is a post-processing NER/regex layer safer than GPT-5 inference?

══════════════════════════════════════════════════════════
SECTION 2 — MULTI-COMPLAINT AND MULTI-SPEAKER ENCOUNTERS
══════════════════════════════════════════════════════════
2.1 Multiple concurrent complaints
    Hand fracture + eye pain + stomach cramps in flat, undifferentiated transcript.
    → How do CTC systems fail when complaints interleave?
    → Chunking/re-ranking strategies for the interpreter to identify complaint boundaries?

2.2 Speaker diarization — absence and implications
    Nurse + patient + family member all merged.
    → Clinical risk of attributing family-reported symptoms to the patient?
    → Evaluate pyannote-audio 3.x on short (2–10 min) noisy Jamaican clinical audio.
    → Minimum viable diarization solution for $0.50/hr L4 GPU budget?

2.3 Doctor medication dictation mid-consultation
    "Give her Augmentin 625 twice daily" appears in same stream as patient complaint.
    → Linguistic cues to distinguish doctor orders from patient statements?
    → Evaluate two-pass approach: extract doctor instructions first, then patient statements.

══════════════════════════════════════════════════════════
SECTION 3 — DIALECTAL AND PHONETIC FAILURE MODES
══════════════════════════════════════════════════════════
3.1 Native Jamaican nouns: folk medicine terms, local food names, parish names, bush remedies
    → Taxonomy of lexical categories the "jam" adapter lacks training data for?
    → Data augmentation without full retrain (hotword biasing, character n-gram LM)?

3.2 Phoneme boundary errors on Patois polysyllables
    "cerasee" → "sera see" | "bissy" → "bis see" | "likkle" → "lik kle"
    → Root cause at CTC decoding level?
    → Edit-distance post-processing for common Patois word splits?

3.3 Code-switching Patois/English mid-sentence
    Single "jam" adapter degrades on standard English segments.
    → Evaluate: SeamlessM4T v2, Whisper large-v3, custom code-switched CTC model.
    → Minimal labelled dataset + synthetic data strategy for fine-tuning Whisper on Jamaican?

3.4 Soft-spoken and quiet patients (elderly, in pain, sensitive topics)
    → Best audio preprocessing (DeepFilterNet, RNNoise, spectral gating) for clinic audio?
    → SNR threshold at which MMS output becomes clinically unusable?

══════════════════════════════════════════════════════════
SECTION 4 — DIAGNOSTIC DISAGREEMENT AND EPISTEMIC CONFLICTS
══════════════════════════════════════════════════════════
4.1 Patient self-diagnosis vs clinical reality
    "Mi have di flu" (6×) vs doctor's one statement "this is pneumonia".
    GPT-5 may weight frequency over the clinician's single assessment.
    → Prompt structure to prevent patient self-diagnosis contaminating Assessment section?
    → Should Subjective echo the patient's belief while Assessment reflects only the clinician?

4.2 CTC confidence vs clinical certainty — hallucination cascade
    Low logit confidence → passes as ground truth → interpreter makes it fluent →
    GPT-5 "corrects" it to plausible medicine → SOAP looks confident → clinician trusts it.
    → How to expose CTC token confidence into uncertainty markers [unclear: confidence=0.34]?
    → Threshold for [LOW CONFIDENCE TRANSCRIPTION] flag?

4.3 Temporal ambiguity
    "Since Christmas", "from di hurricane" — MMS doesn't preserve turn boundaries.
    → Relative time resolution using encounter date as anchor?
    → Clinical risk of missing onset duration in HTN, DM, URTI, antenatal notes?

══════════════════════════════════════════════════════════
SECTION 5 — INFORMATION EXTRACTION AND RELEVANCE FILTERING
══════════════════════════════════════════════════════════
5.1 Nurse asks same question 3–4× before useful answer; all repetition goes to GPT-5 equally.
    → Abstractive pre-summarisation before SOAP — risk of losing clinical signal?
5.2 15-min consult: 3 min clinical, rest small talk/payment/noise.
    → Relevance filtering: VAD level vs transcript classification vs GPT-5 system prompt?
5.3 Patient volunteered a symptom early; later denies further symptoms; doctor misses the first.
    → Doctor-elicited vs patient-volunteered information hierarchy in SOAP generation?

══════════════════════════════════════════════════════════
SECTION 6 — PATIENT SAFETY AND LIABILITY
══════════════════════════════════════════════════════════
6.1 Worst-case scenarios — for each: (a) pipeline failure, (b) note error, (c) clinical consequence,
    (d) why human review might miss it:
    - "Start metformin" (no dose) → GPT-5 writes "Metformin 500mg OD" → copied to EMR
    - "Chest pain radiating to arm" → MMS: "best pain irritate to farm" → no alert fires
    - Drug allergy said quietly → MMS silence → allergy not captured
    - Patient pain 2/10 → note 8/10 → unnecessary clinical escalation
    - Two patients, no session reset → second patient's Sx in first patient's note
    - Cerasee transcribed, not flagged; patient on Metformin → missed interaction
    - "Mi nuh have no pain" → GPT-5 writes "patient reports pain"

6.2 Patois double-negative: "Mi nuh have no" = I have none; English NLP parses as affirmation.
    → Failure rate of English negation detectors on Patois? Fix at interpreter vs GPT-5 stage?

6.3 Legal: Jamaica's medico-legal standards for AI notes? Audit trail to protect clinicians?

══════════════════════════════════════════════════════════
SECTION 7 — COMPARATIVE ANALYSIS
══════════════════════════════════════════════════════════
Compare WellNest to: Nuance DAX Copilot, Freed AI, DeepScribe, Abridge, Suki, Siro.
For each: multi-complaint handling, numeric integrity, negation, patient belief vs diagnosis.
Note where the Patois/dialect challenge makes direct comparison inapplicable.
Commercial scribes extract structured JSON (symptoms, negatives, medications) BEFORE
prose generation — LLM only formats already-validated facts. How does this eliminate
hallucination classes our pipeline cannot address?

══════════════════════════════════════════════════════════
SECTION 8 — FINE-TUNING AND MODEL IMPROVEMENT
══════════════════════════════════════════════════════════
8.1 MMS without labelled corpus: pseudo-labelling, SpecAugment, GPT-4o-generated Patois
    dialogues + TTS for synthetic audio. Fine-tune only "jam" adapter weights — compute cost?
8.2 GPT-5 prompt optimisation (fine-tuning unavailable on Azure): chain-of-thought, few-shot
    Jamaican examples, JSON schema, RAG from Jamaican Formulary. "Lost in the middle" limit?
8.3 GPT-4o-transcribe fine-tuning (Azure-supported): minimum labelled hours? WER gain vs MMS?

══════════════════════════════════════════════════════════
SECTION 9 — EVALUATION METRICS
══════════════════════════════════════════════════════════
9.1 WER vs Medical Concept Error Rate (MCER) for Patois ASR. Gold-standard test set without corpus?
9.2 Interpreter quality: human rubric (Jamaican nurse / doctor / linguist). BERTScore on Patois?
9.3 SOAP faithfulness: QAFactEval / FactScore / bespoke. Acceptable hallucination rate? A/B design?
9.4 Safety red-lines: critical finding recall, medication error rate, negation accuracy thresholds.

══════════════════════════════════════════════════════════
SECTION 10 — PRIORITISED IMPROVEMENT ROADMAP
══════════════════════════════════════════════════════════
Roadmap ordered by: (1) patient safety impact, (2) feasibility 3-person/$500mo, (3) quality/effort.
Per item: stage affected · complexity · validation needed · safety regression risks.
Close with ≤300 word MOH clinical governance executive summary.

══════════════════════════════════════════════════════════
SECTION 11 — 50 PIPELINE GAPS (rate severity + mitigation for each)
══════════════════════════════════════════════════════════
SEVERITY KEY: C=CRITICAL (patient safety) H=HIGH (note accuracy) M=MEDIUM W=LOW

ACOUSTIC (1–15)
GAP 01 [C] Greedy CTC, no LM rescoring — torch.argmax picks frame winner, no medical word preference
GAP 02 [H] No VAD — silence/cough chunks sent to MMS, return garbage phonemes to interpreter
GAP 03 [H] 25-second fixed boundary splits mid-word and mid-sentence without speech-boundary detection
GAP 04 [H] No cross-chunk context overlap — symptoms split across chunks are semantically incomplete in both
GAP 05 [M] Phone-quality audio upsampled to 16kHz — spectral artifacts degrade WER significantly
GAP 06 [H] No noise suppression — AC units, TV, waiting room, street noise all reach MMS
GAP 07 [H] No dynamic range normalisation — quiet elderly speakers underrepresented vs loud nurse
GAP 08 [H] Mobile mic directional bias — nurse voice 3× louder; patient responses partially missed
GAP 09 [C] No CTC confidence surfacing — low-confidence phonemes passed as ground truth to interpreter
GAP 10 [H] "jam" adapter not trained on medical vocabulary — drug names, anatomical terms, lab values
GAP 11 [M] No start/stop detection — pre/post-consultation audio included in transcript
GAP 12 [W] WebM codec artifacts at session start — phantom words in first chunk
GAP 13 [H] No audio quality gate — muffled/pocket recordings accepted and sent to inference
GAP 14 [M] Mono downmix discards stereo spatial cues that could aid diarization
GAP 15 [M] Background music/TV transcribed as speech — phantom clinical words inserted

LINGUISTIC (16–30)
GAP 16 [C] Patois double-negative "mi nuh have no pain" parsed as affirmation — symptom denial → report
GAP 17 [H] Aspect marker "a" misread as article — "mi belly a hurt" temporal meaning altered
GAP 18 [H] Code-switching mid-sentence degrades "jam" adapter — English words get phoneme errors
GAP 19 [M] Parish/place names mangled — epidemiological exposure history unreliable
GAP 20 [C] Herb lookup has only 8 entries — hundreds of Jamaican bush remedies have drug interactions
GAP 21 [H] Patois numerals ("wan","tu","tri") transcribed as non-numeral phoneme strings
GAP 22 [M] Relative time anchors ("from Christmas","since di hurricane") unresolvable without context
GAP 23 [H] Rural deep Patois (St. Elizabeth, Portland) vs Kingston creole — higher WER in rural speakers
GAP 24 [M] Paediatric Patois — "pickney","him" gender-neutral — child gender may be misassigned
GAP 25 [H] Metaphorical symptoms ("chest heavy like stone","something a bite mi inside") need recovery
GAP 26 [M] Social determinants in cultural shorthand ("mi walk come","mi a yard") not extracted as SDoH
GAP 27 [H] Drug names with Jamaican phonology — "Augmentin"→"aug-MEN-tin" — no match in MMS training
GAP 28 [C] Sensitive-topic whispered deep Patois — dual failure: low volume + maximum dialectal deviation
GAP 29 [H] Pronoun "im" gender-neutral — symptom attribution to wrong person in multi-speaker context
GAP 30 [C] Tense markers alter urgency — "mi did have pain" (past, resolved) vs "mi a have pain" (now)

PIPELINE / DATA FLOW (31–40)
GAP 31 [H] Qwen3-1.7B context window overflow — long consultations silently truncated at tail
GAP 32 [C] Interpreter LLM hallucination — adds plausible symptoms/diagnoses not in transcript
GAP 33 [H] GPT-5 frequency bias — patient says "flu" 6× vs doctor says "pneumonia" once; flu wins
GAP 34 [H] No session-level context — prior meds, known allergies, chronic conditions not in prompt
GAP 35 [C] No session reset detection — second patient's symptoms appended to first patient's note
GAP 36 [M] No duplicate detection — same patient in two recording segments → duplicate SOAP entries
GAP 37 [H] No medication reconciliation — plan may prescribe drug patient already takes or that interacts
GAP 38 [H] No real-time transcript preview — nurse cannot correct MMS errors before cascade begins
GAP 39 [M] No feedback loop — doctor note corrections not used to improve future transcriptions
GAP 40 [H] Audit trail doesn't link SOAP sentence → transcript span → ASR phoneme

SAFETY / GOVERNANCE (41–50)
GAP 41 [C] Critical alert fires on exact phrase match — "best pain irritate to farm" misses chest pain alert
GAP 42 [C] No numeric range validation — "BP 280/140" or "Metformin 5000mg" passes unchecked
GAP 43 [C] No drug NER post-generation — hallucinated or misspelled drug names not detected
GAP 44 [C] No dedicated allergy extraction — allergy capture depends entirely on GPT-5 attention
GAP 45 [H] Verifier disabled by default (SCRIBE_VERIFIER_ENABLED=False) — no production hallucination rate
GAP 46 [H] AI disclaimer at note end — doctor may sign without reading; no mandatory acknowledgement
GAP 47 [H] No minimum transcript length gate — 5-second accidental recording → GPT-5 hallucinates full SOAP
GAP 48 [M] No distressed-patient acoustic detection — crying/hyperventilating → MMS accuracy collapses
GAP 49 [M] SOAP Plan may suggest drugs absent from Jamaican National Formulary or local clinic stock
GAP 50 [H] No adversarial input testing / red-team protocol conducted to date

══════════════════════════════════════════════════════════
SECTION 12 — TRUST CHAIN VS VERIFICATION CHAIN
══════════════════════════════════════════════════════════
Current pipeline = TRUST CHAIN: MMS → Interpreter → GPT-5. Each stage treats prior output
as ground truth. The worst failure mode is "cascading plausibility": slightly wrong ASR →
interpreter makes it fluent → GPT-5 normalises it into confident SOAP → clinician trusts it.

VERIFICATION CHAIN inserts a structured gate:
  MMS → Interpreter → [IR extraction + validation] → GPT-5
Commercial scribes extract JSON BEFORE prose: {symptoms[], negatives[], medications[{name,dose,freq}],
vitals:{bp:null if not stated}}. LLM only formats already-validated facts.

→ For each boundary (MMS→Interp, Interp→GPT-5, GPT-5→UI): what error classes pass silently?
   What minimum gate converts trust to verification?
→ Design the IR JSON schema for Jamaican primary care. Compare extraction by:
   Qwen3-1.7B (cheap) vs dedicated GPT-5 call (accurate) vs rule-based (deterministic).
→ Validation rules: mandatory fields, numeric ranges, negatives-vs-symptoms consistency,
   failure handling (hard reject vs soft flag vs partial generation).

══════════════════════════════════════════════════════════
SECTION 13 — CARIBBEAN DIALECT EXTENSION (BAJAN + OECS)
══════════════════════════════════════════════════════════
The same problem exists across the English-speaking Caribbean. Analyse Barbadian (Bajan)
Creole as the primary expansion target, then Trinidad, Guyana, Saint Lucia.

BAJAN VS JAMAICAN (key differences):
- Pronouns: "wunnuh" (y'all, unique to Bajan); "he" as generic 3rd person
- Negation: "ain't have no" (double-neg "ain't" vs Jamaican "nuh")
- Aspect: "he DOES have chest pain every morning" (Bajan habitual = chronic condition)
  vs Jamaican "him a have chest pain" (progressive aspect "a")
- Bajan-specific clinical vocab (≥20 items needed):
  Food: cou-cou, flying fish, pudding and souse · Herbs: wonder of the world (Kalanchoe),
  wild sage, vervain, bay rum · Time: "since Crop-Over" · Social: "working in canes"
  (leptospirosis), "does fish" (marine exposure) · Health: "a lil poorly", "wuh happen?"

→ Expected WER of "jam" adapter on Bajan (estimate from phonological distance)?
   Does MMS-1b-l1107 include "bbs" adapter? If not, best alternative?
→ Public Bajan audio sources: CBC Barbados, UWI Cave Hill recordings.
→ Rewrite interpreter prompt for Bajan: "ain't" negation, Bajan herb table, Barbados
   Formulary, QEH as sole tertiary referral.
→ Barbadian clinical context: leptospirosis from cane fields, sickle cell prevalence,
   lowest dengue rate in major Caribbean islands.

BROADER CARIBBEAN (one line each):
- Trinidad: French Creole substrate; "tabanca"=heartbreak stress; "dotish"=confused (AMS); Hindi loanwords
- Guyana: Hindustani loanwords; high Indo-Guyanese DM; "mash up"=injured
- Saint Lucia: Kwéyòl mid-sentence switches = total MMS failure; "bolom"=spirit for unexplained Sx
- Cayman: nearest to standard English; dive injuries (decompression sickness)

→ One pan-Caribbean model vs per-territory configs? Evaluate: accuracy, cost, legal
  compliance (Jamaica JDPA 2020, Trinidad DPA 2011, Barbados DPA 2021), maintainability.
→ Expansion priority: by population (TT→GY→BB→OECS) or linguistic proximity (BB→TT→GY)?
```

*WellNest Scribe R&D — June 2026 — Internal use only*
