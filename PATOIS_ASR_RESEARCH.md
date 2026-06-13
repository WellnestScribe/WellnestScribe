# WellNest Scribe — Patois ASR/NLP Research Brief

## Purpose
This document is a prompt for an AI researcher. Read the full pipeline description,
then answer the questions at the bottom. The goal is to identify linguistic failure
modes, clinical safety risks, and gaps in the current system before wider deployment.

---

## What We Are Building

WellNest Scribe is a clinical documentation tool for Jamaican healthcare providers.
A doctor records a patient consultation in audio. The audio is transcribed and
converted into a structured SOAP note (or narrative/chart note) automatically.

The patient speaks **Jamaican Patois (Patwa)**, a creole language with its own
phonology, grammar, tense system, negation patterns, and discourse markers.
The ASR model (Facebook MMS) outputs a **phonetic approximation** of the speech —
not standard English, not standard Patois spelling. It writes what it hears.

---

## The Pipeline

```
[Doctor + Patient audio]
        │
        ▼
[MMS ASR model]
  → raw phonetic transcript (Patwa tokens spelled phonetically in Latin script)
  → example: "ipien levl iz a siks nou iz ant iz a iet out a ten"
        │
        ▼
[Patois Interpreter LLM — PATOIS_INTERPRETER_SYSTEM_PROMPT]
  Three mandatory steps:
  STEP 1 — PHONETIC RESOLUTION: token-by-token word mapping
  STEP 2 — ASSEMBLED ENGLISH: grammatical English sentences
  STEP 3 — CLINICAL INTERPRETATION: structured clinical fields
  → outputs Step 2 clean English for display + SOAP generation
        │
        ▼
[SOAP Generator LLM — JAMAICAN_CONTEXT_ADDENDUM + SOAP prompts]
  → receives Step 2 assembled English as the "transcript"
  → outputs structured SOAP note (S/O/A/P + summary)
        │
        ▼
[Doctor reviews, edits, finalises note]
```

---

## Known Failure Modes (Already Encountered)

### 1. `nou` ambiguity
"nou" in Patois = "no" (correction marker) OR "now" (temporal). The LLM
consistently misreads it as "now" when it appears between two numbers.

Real example:
```
"ipien levl iz a siks nou iz ant iz a iet out a ten"
```
Correct meaning: Patient said "pain level is 6 — no — it's an 8 out of 10."
(Self-correction. Active score = 8/10.)

LLM keeps outputting: "pain level is 6 now, was 8 before."
(Treats as temporal progression. Active score = 6/10 — clinically wrong.)

Attempted fixes: added disambiguation rules to PATOIS_INTERPRETER_SYSTEM_PROMPT,
added the exact utterance as a worked example, added to FINAL REMINDERS.
Still failing as of latest test.

### 2. `iz ant iz` mis-parsed
"iz ant iz" = speech stutter/restart ("it's not… it's"). Patient backing up
to correct themselves. The LLM reads it as a double-negative (negation of the
second value) rather than a restart.

### 3. Negation in general
Patois uses "nuh/nah/na" for negation. Double-negatives in Patois = single
negation ("mi nuh have no pain" = patient has NO pain). LLM with English
training tends to cancel the double-negative incorrectly.

### 4. Tense markers misread as present
"mi did have pain" (PAST — may be resolved) vs "mi a have pain" (ONGOING NOW).
Mixing these up changes clinical urgency significantly.

### 5. Minimising language
Jamaican patients culturally downplay symptoms: "likkle likkle pain", "a nuh
nutten". The LLM may record "mild pain" when the patient is minimising something
significant (and presenting to clinic despite it).

---

## System Constraints to Know

- The interpreter and SOAP generator are different LLM calls (different prompts).
- The doctor CAN edit the Step 2 transcript before regenerating the note.
- Numerical values (pain scores, BP, doses, durations) are the highest-risk fields.
- The system appends an AI disclaimer to every note.
- Notes are labelled "Ready for review" — not auto-finalised.
- The doctor is the final reviewer and the medico-legal author of the note.

---

## Research Questions

Please analyse the pipeline and address ALL of the following:

### A. Linguistic failure modes we haven't thought of yet
1. What other Patois phonetic patterns are likely to cause systematic
   misinterpretation by an LLM trained predominantly on English?
2. What tense/aspect constructions in Patois (beyond "mi did" / "mi a") could
   be misread in ways that change clinical meaning?
3. What negation or double-negative patterns beyond "nuh/nah" are common in
   Jamaican Patois and could cause dangerous inversions of clinical findings?
4. Are there Patois discourse markers or sentence structures that look like
   symptoms but aren't — or vice versa?
5. What body-part terms in Patois are most likely to be phonetically transcribed
   in a way that resembles an unrelated English word?

### B. Numerical value safety
6. What patterns in Patois speech could cause the system to fabricate,
   invert, or lose a numerical value (pain score, BP reading, medication dose,
   gestational age, duration)?
7. How should the system handle a patient who gives contradictory numbers
   (e.g. reports pain as 7/10 in one breath and 4/10 later without a clear
   self-correction signal)?
8. What is the safest default when a numerical value is ambiguous — record
   both, flag it, use the higher value (conservative), or use the lower?

### C. The `nou` problem specifically
9. Is there a more robust way to resolve `nou` ambiguity than prompt rules?
   For example: could a pre-processing regex/rule reliably detect the
   `[number] nou [restart] [number]` pattern before the LLM sees it?
10. What surrounding context clues reliably distinguish "nou = no (correction)"
    from "nou = now (temporal)" in a phonetically transcribed Patois text?

### D. Pipeline architecture risks
11. The pipeline converts raw Patois → Step 2 English → SOAP note in two
    separate LLM calls. What information is at risk of being lost or distorted
    at each handoff?
12. If Step 2 assembles an incorrect English sentence (wrong pain score,
    wrong medication name, wrong body part), the SOAP generator has no way
    to detect it — it treats Step 2 as ground truth. How serious is this risk
    and how could it be mitigated?
13. Should the SOAP generator ever see the raw Patois alongside Step 2, as
    a cross-check? What are the trade-offs?

### E. Clinical safety and usability
14. Given everything above, is this system safe to use as a clinical
    documentation aid (doctor reviews every note before finalising)?
    What conditions would make it unsafe?
15. What are the highest-risk specialties or encounter types where this
    pipeline is most likely to produce a clinically dangerous error?
16. What automated checks (not LLM-based) could be added as a safety net —
    e.g. pattern matching, value-range checks, flag-on-uncertainty logic?
17. Is there a better architecture for this specific language/task combination
    than the current three-step interpreter → SOAP generator chain?

### F. Creole/low-resource language considerations
18. Are there lessons from NLP research on other creole or low-resource
    languages (Haitian Creole, Nigerian Pidgin, Singlish) that apply here?
19. MMS was trained on a wide range of languages but Patois is not a
    standardised written language. What systematic biases would you expect
    in MMS output for Jamaican Patois speech specifically?
20. What would a more robust long-term approach look like — e.g. fine-tuning
    a Patois-specific ASR model, building a Patois normalisation layer, or
    collecting a labelled correction dataset?

---

## What a Good Response Looks Like

- Address each question directly, even if briefly.
- Flag any question where you are uncertain or where the answer depends on
  empirical testing we haven't done.
- Prioritise by clinical risk: highest-risk failure modes first.
- Be honest about the limits of prompt engineering for this task.
- Suggest concrete, implementable improvements where possible.
- At the end, give an overall verdict: is the current system safe enough for
  supervised clinical use, and under what conditions?
