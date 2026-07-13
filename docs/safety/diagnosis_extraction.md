# Diagnosis extraction — clinical-safety design

**Status:** active safeguard · **Owner:** clinical safety · **Last reviewed:** 2026-07-13

This document explains how a coded diagnosis (ICD-10) reaches a patient's
Problem List, the safety incident that motivated the current guards, and every
edge case the extractor is designed to survive. It is deliberately blunt:
a wrongly-coded diagnosis is a legal record that says a patient *has* a disease
they do not have, and can directly cause harm (wrong drug, wrong dose, denied
insurance, wrong downstream decision).

## The incident that triggered this

A patient was seen for **left ankle pain**. During the visit the patient said,
in effect, *"I have hypertension and take tablets daily, but I do not have
diabetes."* The finalized note correctly recorded **"PMH: Hypertension. Denies
diabetes."**

Despite that, the Problem List auto-populated with:

- `I10` Essential hypertension — correct
- `E11.9` **Type 2 diabetes mellitus** — **WRONG. The patient denied it.**
- `J06.9` **Acute upper respiratory infection** — **WRONG. Never discussed.**

Two distinct bugs combined:

1. **No negation awareness.** The old extractor did a plain substring search for
   `"diabetes"`. The strings *"denies diabetes"* and *"do not have diabetes"*
   both contain `"diabetes"`, so the code was minted from a denial.
2. **Substring matching without word boundaries.** The respiratory-infection
   matcher included the keyword `"uri"`. `"uri"` is literally inside the word
   **"during"** (and *urine*, *capturing*, *measuring*…), so an unrelated word
   produced a phantom respiratory diagnosis.

A third, deeper problem: the extractor searched the **raw transcript and the
patient's verbatim chief complaint**, so a diagnosis could be born from what the
*patient* said rather than what the *doctor* concluded.

## How the Problem List is actually built

Diagnoses are **not** produced by the AI note generator. They come from a
deterministic keyword extractor in
[`apps/emr/services/scribe_import.py`](../../apps/emr/services/scribe_import.py):

- On **finalize**, `materialize_encounter_from_session()` builds an EMR encounter
  and calls `build_scribe_import_bundle()` → `_extract_diagnoses()`.
- `_extract_diagnoses()` walks a fixed table (`DIAGNOSIS_MATCHERS`) of ~9 common
  conditions, each with keywords and an ICD-10 code, and writes matching
  `Diagnosis` rows (`ai_suggested=True`) into the draft encounter.
- Those rows render as the patient's Problem List.

Because it is deterministic (no model), its behaviour is fully auditable and
testable — which is exactly why it is the right layer to enforce hard safety
rules.

## The ground-truth principle

**The doctor is ground truth. A coded diagnosis must reflect what the clinician
confirmed, never what the patient said.** A patient may deny a condition they
actually have, or claim one they don't — only the doctor's confirmed impression
(the Assessment) is authoritative.

## Primary path: AI-coded from the Assessment

A keyword regex cannot *reason* — it cannot tell "the doctor confirmed diabetes
despite the patient denying it" from "the patient denies diabetes." So diagnosis
coding is now driven by the note generator, which understands that distinction:

- The generation prompt instructs the model to append the ICD-10 code to each
  **Assessment** line the doctor confirmed, e.g.
  `1. Hypertension (uncontrolled) (ICD-10 I10)`. Codes use parentheses (not
  `[brackets]`) so they don't collide with the placeholder-fill UI.
- The prompt explicitly forbids coding a condition the patient "merely mentioned,
  denied, or that belongs to family history." Because such conditions never enter
  the Assessment, they are never coded — no regex negation logic required.
- `_parse_ai_coded_diagnoses()` reads those tags into the Problem List. Codes are
  format-validated (`^[A-TV-Z][0-9][0-9AB](\.…)?$`); an unsure `(ICD-10 ?)` or a
  malformed code stores the description with **no code** and raises a review flag
  for the clinician to complete. The encounter is still a draft the doctor signs.

## Fallback path: deterministic keyword extractor

For older notes that carry no ICD tags, coding falls back to the deterministic
`_extract_diagnoses`, which reads **only** the clinician's written note
(Assessment/Plan/Subjective, or full note) — never the raw transcript or the
patient's verbatim chief complaint — and applies every guard below.

## Safety rules now enforced

Every candidate diagnosis passes these gates before it can be coded
(`_extract_diagnoses`, `_classify_diagnosis`, `_has_cue`, `_clause_around`):

1. **Word-boundary matching.** Keywords match on `\bword\b`. `"uri"` can never
   fire inside `"during"`; `"uti"` can never fire inside `"gratuity"`.
2. **Negation guard.** If the clause containing the term carries a negation cue
   (*denies, no, not, without, never, no known, no history of, negative for,
   ruled out, resolved, no longer,* plus Patois *nuh have / nah have*), the
   diagnosis is **not coded**.
3. **Family-history guard.** If the clause names a relative (*father, mother,
   sibling, family history, maternal/paternal…*), the condition belongs to the
   relative and is **not coded** for this patient.
4. **Uncertainty → suspected.** If the clause is hedged (*possible, probable,
   suspected, query, rule out, r/o, consider, likely, differential*), the
   diagnosis is coded with status **suspected**, never *active*/*chronic* — so it
   is never asserted as established fact.
5. **Clause-scoped negation.** Negation is evaluated within the clause only,
   bounded by *but / however / commas / semicolons*, so *"no chest pain **but**
   has cough"* does not suppress the cough.
6. **No silent drops.** When a term is skipped (rules 2–3), the extractor raises
   a **review flag** on the encounter — e.g. *"'Type 2 diabetes' was mentioned
   but NOT auto-added — it appears negated or attributed to family history. Add it
   manually only if the patient actually has it."* The clinician sees that a
   decision was made and why. Nothing is coded silently, and nothing dangerous is
   dropped silently.
7. **Known-condition conflict flag.** A chronic condition already on file
   (`session.active_conditions`) is still honoured — **unless** this visit's note
   denies it, in which case it is held back and flagged: *"'Diabetes' is on the
   known-conditions list but appears denied in this visit — confirm before
   keeping it on the Problem List."*
8. **Provenance is recorded.** Every coded diagnosis stores the exact source
   sentence it was derived from (`Diagnosis.notes`) and is marked
   `ai_suggested=True`, so the clinician can see and verify the basis for each
   entry in both edit and view mode before signing.

## Edge-case catalogue

| # | Scenario | Example | Handling |
|---|----------|---------|----------|
| 1 | Denied condition | "denies diabetes", "I do not have diabetes" | **Not coded**, review flag raised |
| 2 | Substring collision | "uri" inside "during" | **Not matched** (word boundary) |
| 3 | Family history | "father has diabetes" | **Not coded**, review flag raised |
| 4 | Resolved / historical | "pneumonia last year, resolved" | **Not coded** (resolved/no-longer cue) |
| 5 | Ruled out | "DVT ruled out", "negative for TB" | **Not coded** |
| 6 | Differential / hedge | "possible fracture", "query MI" | Coded as **suspected**, not active |
| 7 | Cross-clause negation | "no chest pain but has cough" | Only the cough codes |
| 8 | Patois negation | "mi nuh have sugar" | **Not coded** (nuh have) |
| 9 | Patient words only | condition appears only in transcript / chief complaint | **Not read** — clinician sections only |
| 10 | Known condition denied today | dm on file, patient denies this visit | Held back + conflict flag |
| 11 | Screening ≠ diagnosis | "diabetes screening", "BP review" | Reason-for-visit keywords are separate; a bare disease term still requires the clinician's note to assert it |

## What is intentionally NOT done (and why)

- **We under-code on purpose.** If the doctor only mentioned a chronic condition
  in the raw transcript and never wrote it into the note, it will not
  auto-appear. That is the safe direction: the clinician can add a real
  condition in one click, but an auto-added *wrong* condition can hurt someone.
- **No AI in this path.** Coding stays deterministic so it is auditable and can
  be unit-tested. AI is used for the narrative note, not for minting ICD codes.

## Residual risks / future work

- **Allergies are not auto-extracted** into the EMR here (they are entered
  manually), so the negation-flip risk does not exist in this path today. If
  allergy auto-import is ever added, it **must** reuse the same negation guard —
  "no known drug allergies" must never become a coded allergy.
- **Laterality** (left vs right) is carried in the free-text note but not yet
  validated against structured fields.
- The negation cue list is heuristic. It is intentionally biased toward
  *skipping* (flagging) rather than coding when ambiguous.
- Add unit tests mirroring the edge-case table above so regressions are caught in
  CI.
