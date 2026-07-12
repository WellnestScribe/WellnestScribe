# WellNest Scribe — Caribbean Creoles Research Brief

## Purpose

This document is a prompt for an AI researcher. WellNest Scribe is currently
optimised for Jamaican Patois (Patwa). We are expanding to other Caribbean
territories where patients speak different creoles, and we need to identify
failure modes *before* deployment — not after a clinical error occurs.

Read the pipeline description, then answer all questions. Address each one
directly, even if briefly. Flag where you are uncertain.

---

## Background: The Pipeline

```
[Doctor + Patient audio]
        │
        ▼
[MMS ASR model — Facebook Massively Multilingual Speech]
  → raw phonetic transcript in Latin script
  → MMS has NO Patois-specific training; output is phonetic approximation
        │
        ▼
[Pre-processor — deterministic Python regex layer]
  Rewrites known failure patterns before the LLM sees the text:
  - "nou" self-correction: [number] nou [restart] [number] → [SELF-CORRECTION annotation]
  - kyaan/kaan variants → [CANNOT annotation]
  - woulda/wuda → [CONDITIONAL-not-definite annotation]
  - Discourse markers → [DISCOURSE MARKER annotation]
  - BP verbal patterns: "wan-twenty ova eighty" → [BLOOD PRESSURE READING annotation]
  - Approximation markers: "bout seben" → [APPROXIMATE VALUE ~7 annotation]
        │
        ▼
[Patois Interpreter LLM — PATOIS_INTERPRETER_SYSTEM_PROMPT]
  Three mandatory steps:
  STEP 1 — PHONETIC RESOLUTION: token-by-token word mapping
  STEP 2 — ASSEMBLED ENGLISH: grammatical English sentences
  STEP 3 — CLINICAL INTERPRETATION: structured clinical fields
  Outputs Step 2 clean English for display + SOAP generation
  Embeds [UNCERTAIN: ...] tags for ambiguous values
        │
        ▼
[SOAP Generator LLM — JAMAICAN_CONTEXT_ADDENDUM + SOAP prompts]
  → receives Step 2 assembled English as the "transcript"
  → preserves [UNCERTAIN: ...] flags — does NOT resolve them
  → outputs structured SOAP note
        │
        ▼
[Post-generation validators — deterministic, zero API cost]
  - Pain score range check (0–10)
  - BP range check (systolic 60–250 / diastolic 40–150)
  - Gestational age range check (4–44 weeks)
  - Contradictory pain score detector
  - Missing vitals in Objective
  - Minimising language keyword detector on raw transcript
        │
        ▼
[Doctor reviews, edits, finalises note — medico-legal author]
```

---

## Known Failure Modes (Jamaican Patois, Already Addressed)

These have been documented and partially mitigated. Use them as a baseline
for what types of problems to look for in other creoles:

1. **"nou" ambiguity** — Patois "nou" = "no" (correction marker) or "now" (temporal).
   Fixed with pre-processor regex.
2. **Negation inversion** — "mi nuh have no pain" = NO pain (Patois double-negative
   = single negation). LLM defaults to English grammar and reads as positive.
3. **"iz ant iz" stutter restart** — misread as double-negative. Documented.
4. **Tense/aspect markers** — "mi did have" (past) vs "mi a have" (ongoing now).
5. **Minimising language** — "likkle likkle", "a nuh nutten" = patient downplaying.
6. **Body-part semantic scope** — "foot" in Patois = entire lower limb.
7. **"woulda"** — conditional/hypothetical, not a definite current symptom.
8. **Phonetic body-part confusions** — "haart"→heart, "bres/brehs"→chest.
9. **BP verbal patterns** — "wan-twenty ova eighty" = 120/80.
10. **"kyaan/cyan"** — cannot. MMS may output as "cyan" or "can" (opposite meaning).

---

## Caribbean Creoles to Analyse

Please analyse each of the following for the same failure mode categories.
These are the most likely expansion territories for WellNest Scribe:

### Primary targets (high population, likely near-term deployment)

| Territory | Primary patient language | Notes |
|---|---|---|
| Barbados | Bajan Creole (Bajan) | English-based creole, distinct phonology |
| Trinidad & Tobago | Trinidadian Creole English / Trinbagonian | Mix of influences; heavy code-switching |
| Guyana | Guyanese Creole (Creolese) | Similarities to Jamaican but distinct |
| Belize | Belizean Creole (Kriol) | English-based, unique lexicon |
| St Lucia | Antillean Creole French (Kwéyòl) + English | French-based; bi-lingual patients |
| Haiti | Haitian Creole (Kreyòl ayisyen) | French-based; largest Caribbean creole speaker population |

### Secondary targets

| Territory | Primary patient language | Notes |
|---|---|---|
| Dominica | Dominican Creole French / English | Similar to St Lucia Kwéyòl |
| Grenada | Grenadian Creole English | English-based, Trinidad-adjacent |
| St Vincent | Vincentian Creole English | English-based |
| Suriname | Sranan Tongo / Dutch | Not English-based; very different from others |
| Antigua | Antiguan Creole English | English-based |

---

## Research Questions

### A. Per-creole linguistic profile

For EACH creole listed above, answer:

1. What is the negation system? Does it use double-negation like Jamaican Patois
   (e.g. "mi nuh have no pain" = no pain)? Or does it use single negation?
   Are there creole-specific negation particles the LLM would misread?

2. What are the tense/aspect markers (TMA particles)? Which ones change clinical
   urgency if misread (e.g. past vs. ongoing, conditional vs. definite)?

3. What are the most common body-part terms that do NOT correspond to their
   English phonetic near-homonym? (Same as the "foot" = lower limb problem in
   Jamaican Patois.)

4. Does this creole have a minimising/downplaying register similar to Jamaican
   "likkle likkle"? What are the key phrases?

5. What discourse markers are common in this creole that could be misread as
   symptoms or clinical findings?

6. What self-correction patterns exist? Is there a direct equivalent of the
   Jamaican "nou" (= "no, actually...") that appears between two numbers?

7. How does code-switching work in this territory? Do patients switch between
   the creole and Standard English (or Standard French for French-based creoles)
   mid-sentence, and what is the clinical risk when they do?

### B. MMS ASR behaviour per creole

8. How well does MMS perform on each creole? Is there published benchmarking,
   or can you make an educated assessment based on MMS training data composition?

9. For French-based creoles (Haitian Creole, Kwéyòl), how does MMS handle the
   distinction between French loanwords, creole-specific vocabulary, and
   French itself? Would MMS output look more like French phonetics or English?

10. What systematic phonetic biases would you expect MMS to exhibit for each
    creole? (Same question as the Jamaican MMS bias analysis, per territory.)

### C. Clinical safety risks specific to each creole

11. Are there medication names, herbal remedies, or traditional treatments
    specific to each territory that would be phonetically unusual and likely
    to be misread? (Jamaican equivalents: cerasee, bissy, fever grass, jackass
    bitters — all have local phonetic forms.)

12. Are there culturally specific minimising expressions, stoic presentations,
    or beliefs about illness that a clinician from outside the territory would
    miss? How should the SOAP generator be prompted to flag these?

13. For each creole, what are the highest-risk medical specialties — the same
    way obstetrics, psychiatry, and paediatrics are highest-risk for Jamaican
    Patois? Are there territory-specific epidemiological patterns (e.g. sickle
    cell, dengue, leptospirosis, yellow fever)?

14. Are there pain expression idioms per territory that map to specific
    clinical findings? (Jamaican equivalents: "chest heavy like stone" →
    chest pressure; "something a bite mi inside" → visceral pain.)

### D. Pre-processor rules needed per creole

15. For each creole, what deterministic pre-processor rules (regex-level, no
    LLM required) would you recommend adding to the pipeline? Format as:
    - Pattern to detect
    - What it means clinically
    - How to annotate it before the LLM sees it
    - Clinical risk if missed

16. Which failure modes are SHARED across multiple Caribbean creoles vs. which
    are unique to a single territory? Shared ones should be handled in a
    common layer; territory-specific ones go in territory-specific configs.

17. For the French-based creoles (Haitian Creole, St Lucia Kwéyòl, Dominica),
    should a separate interpreter prompt be written, or can the same Patois
    interpreter prompt be adapted? What would need to change?

### E. Architecture implications

18. The current system has a single `PATOIS_INTERPRETER_SYSTEM_PROMPT` tuned
    for Jamaican Patois. If we add Trinidadian Creole support, for example,
    should we:
    (a) Add Trinidadian-specific sections to the existing prompt?
    (b) Create a separate interpreter prompt per territory?
    (c) Use a routing layer that selects the correct prompt based on
        territory/language metadata from the session?
    What are the trade-offs of each approach?

19. The pre-processor (`_preprocess_patois`) currently contains Jamaica-specific
    rules. Should it be refactored into a territory-aware pre-processor with
    pluggable rule sets? What would the architecture look like?

20. If a patient's creole sits somewhere on a continuum (e.g. light Bajan vs.
    deep Bajan) and the doctor doesn't know which end of the spectrum to expect,
    how should the system handle this? Is there a graceful degradation strategy?

---

## What a Good Response Looks Like

- Address each creole separately — do not merge them.
- For each creole, prioritise by clinical risk: most dangerous failure modes first.
- Be honest about uncertainty: flag where you are extrapolating vs. where
  published NLP/linguistics research exists.
- For each pre-processor rule recommendation (Section D), give the regex pattern
  or a clear enough description that a developer can implement it in Python.
- At the end, give a ranked list: which creole presents the highest risk of
  clinical error if deployed WITHOUT a territory-specific interpreter prompt,
  and why.
- Flag any territory where you believe the current Jamaican Patois pipeline
  would produce DANGEROUS (not just inaccurate) output if used as-is.
