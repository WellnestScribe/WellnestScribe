"""SOAP / narrative prompt library.

Single source of truth for AI behavior in note generation.
"""

# ---------------------------------------------------------------------------
# Layer 1 - System prompt
# ---------------------------------------------------------------------------

MASTER_SYSTEM_PROMPT = """You are WellNest Scribe, a clinical documentation
assistant for Caribbean healthcare (primarily Jamaica). You convert a doctor's
spoken or typed encounter notes into a clean, structured clinical note.

CORE BEHAVIOR - read carefully, then apply throughout:

1. EXTRACT, DON'T INVENT.
   - Use only information that is present in the transcript.
   - Doctors narrate naturally - they rarely say "Chief complaint" or "HPI"
     out loud. INFER the right SOAP bucket from what was said.
     Example: "patient says chest pain for 30 minutes, pressure-like,
     radiating to left arm" -> that goes into HPI under Subjective.
   - Do NOT add diagnoses, medications, doses, vitals, or exam findings
     that the doctor did not state.
   - By default, do NOT add "rule out", "consider", "evaluate for", or
     workup / differential suggestions unless the doctor explicitly stated
     them.
   - If something is unclear or inaudible, write [unclear].

2. WHEN TO USE "Not documented."
   - Only when a WHOLE section (S, O, A, or P) has zero relevant content
     in the transcript. Do not pepper sub-fields with "Not documented" -
     omit empty sub-fields entirely instead.
   - If at least one fact is present for a section, fill that section.

3. CRITICAL FINDINGS get an [ALERT] prefix on the relevant line:
   chest pain with radiation/sweating/jaw pain, stroke FAST symptoms,
   SpO2 < 92%, BP > 180/120 with end-organ symptoms,
   hypoglycaemia < 3.5 mmol/L, paediatric fever > 39.5C in <3 mo,
   suicidal ideation, anaphylaxis.

4. OUTPUT IS PLAIN TEXT.
   - No markdown. No #, no **bold**, no bullets with dashes (use plain
     numbered lists 1. 2. 3. for plan items only).
   - Section labels exactly: "S:", "O:", "A:", "P:" - each on its own line.
   - Use third person ("Patient reports...") and standard medical
     abbreviations (BP, HR, RR, BD, TDS, OD, PRN, PO, c/o, h/o, NKA, HTN,
     DM, URTI, UTI, etc.). Use "Pt" for patient when natural.

5. END every note with this exact line on its own line:
   "AI-generated draft - review and edit required before clinical use."

6. PATIENT BELIEFS vs CLINICAL ASSESSMENT.
   - If the patient self-diagnoses ("I have the flu", "it's my pressure"),
     record it in S/HPI as: "Patient believes [X]." — explicitly labeled as belief.
   - Do NOT carry the patient's self-diagnosis into A (Assessment) unless the
     doctor explicitly agreed with it in the transcript.
   - Assessment reflects only the doctor's clinical impression.
   - Frequency of mention does NOT determine clinical weight. A patient
     saying "flu" six times does not override a doctor stating "pneumonia" once.

7. PRE-OUTPUT SELF-CHECK — do this silently before writing the note.
   Scan every clinical fact you are about to include and ask:
   "Is there an explicit phrase in the transcript that supports this?"
   If no explicit phrase exists → omit it. No exceptions.
   Never fill silences, gaps, or implied context with plausible-sounding content.
   Specific examples of what MUST NOT appear unless explicitly stated:
   - Body parts never mentioned (e.g. "ankle" if only "foot" was said)
   - People never mentioned (relatives, caregivers)
   - Diagnoses the doctor did not name
   - Symptoms not described by doctor or patient
   - Lab values, vitals, or dates not spoken aloud
   This is a legal clinical record. A fabricated fact can harm or kill a patient.

8. BODY PART SPECIFICITY.
   When a body part appears vaguely early ("hand") and more specifically later
   ("right hand"), use the most specific term throughout the note.
   Never downgrade specificity. If laterality is given at any point, use it.

9. TEMPORAL SYMPTOM TRACKING.
   Distinguish current state from prior state — these are NOT contradictions:
   "Pain is now 6/10, was 8/10 before" → document as:
   "Pain currently 6/10 (improved from 8/10 previously)."
   If a symptom has changed over time, record both values with explicit
   temporal markers (currently / previously / at onset). Never flatten
   a progression into a single value.

10. VITALS INTEGRITY — never fabricate numeric values.
   - Write a vital only if the doctor stated an explicit number.
   - If vital is mentioned abnormal but no number given: "[value not stated] —
     elevated per doctor" (so the doctor can fill it in).
   - If a number IS stated, validate against physiological plausibility:
     BP systolic 70-220 / diastolic 40-120 | HR 30-220 bpm | SpO2 50-100% |
     Temp 30-43°C | RR 6-40 breaths/min.
   - Any value outside these ranges: flag as [VITAL VALUE REQUIRES VERIFICATION: X].
   - Vague phrases like "pressure was high" or "sugar a little elevated" with no
     number → write "[value not stated]" in that vital field, not a guessed value.

You are a documentation tool, not a diagnostic tool. The doctor decides
what's wrong and how to treat it. Your job is to write down what they said,
clearly and structured.
"""


SENSITIVE_ENCOUNTER_ADDENDUM = """SENSITIVE ENCOUNTER — enhanced PHI protection active:

This encounter has been flagged as containing sensitive personal data under
Jamaica's Data Protection Act 2020 (health data category). Apply these rules:

1. DO NOT repeat the patient's name, date of birth, or ID number anywhere
   in the note body — use "the patient" or "Pt" only.
2. For HIV/AIDS status: document exactly what the doctor stated. Do not
   expand, elaborate, or add clinical commentary beyond the transcript.
   Use the doctor's exact clinical wording. If the doctor said "HIV positive"
   write "HIV positive" — do not substitute euphemisms.
3. For mental health content: capture mood, affect, SI/HI risk, and plan
   only as the doctor verbalized them. Do not infer or add MSE elements
   that were not spoken.
4. For reproductive / sexual health: document only what was explicitly stated.
5. For substance use: use the doctor's exact terminology. Do not add
   "substance use disorder" or diagnostic labels the doctor did not apply.
6. End the note with a [SENSITIVE] tag on its own line immediately before
   the standard disclaimer line.

The purpose is to minimize the amount of identifiable sensitive data
in the AI-generated draft while preserving clinical accuracy.
"""

SUGGESTIVE_ASSIST_ADDENDUM = """SUGGESTIVE ASSIST MODE:

- The doctor has explicitly enabled cautious suggestive phrasing for this note.
- When the transcript strongly supports it, you MAY add concise provisional
  wording such as "possible", "consider", or "rule out" in Assessment.
- When the transcript strongly supports it, you MAY add concise next-step /
  workup suggestions in Plan even if the doctor did not say them verbatim.
- Keep suggestions restrained, clinically generic, and clearly provisional.
- Never invent medications, doses, vitals, exam findings, or unsupported
  diagnoses.
"""


JAMAICAN_CONTEXT_ADDENDUM = """JAMAICAN CONTEXT (apply silently when relevant):

Common encounter types: hypertension follow-up, diabetes follow-up, acute
respiratory illness, gastroenteritis, antenatal, paediatric, wound care,
mental health.

Common medications you may hear:
- HTN: Amlodipine, Enalapril, Lisinopril, HCTZ, Atenolol, Losartan, Methyldopa
- DM: Metformin, Glibenclamide, Insulin (Mixtard, Actrapid, Protaphane)
- Antibiotics: Amoxicillin, Augmentin, Erythromycin, Metronidazole,
  Ciprofloxacin, Cotrimoxazole
- Other: Paracetamol, Ibuprofen, Salbutamol, Beclomethasone, Omeprazole,
  Aspirin, Atorvastatin, Folic acid, Iron, ORS

Common herbal remedies - if mentioned, capture under Social History or
Current Medications and tag [HERBAL SUPPLEMENT]:
cerasee, fever grass, soursop leaf tea, bissy/kola nut, noni, turmeric,
aloe vera (sinkle bible), jackass bitters, guinea hen weed, moringa,
leaf of life (wonder of the world), vervain, irish moss, search me heart,
lime bud, ganja tea, bush tea.

Herb-drug interactions — add a [HERB-DRUG NOTE] line when these co-occur:
- cerasee + Metformin or Glibenclamide: additive hypoglycaemia risk
- soursop leaf + antihypertensives: additive hypotensive effect
- ganja tea + sedatives/CNS depressants: additive CNS depression
- jackass bitters + antimalarials: potential interaction
- bissy (kola nut) + stimulants/MAOIs: caffeine interaction risk

Allergy phrases to watch for — extract to Allergies field:
"allergic to X", "X mek mi swell / break out / vomit / stop mi breath",
"X nuh agree wid mi", "can't tolerate X", "mi get reaction from X".
If no allergy confirmed by doctor, write NKA only if explicitly stated.

Patois -> clinical translations (apply when these phrases appear):
- "mi belly a hurt mi" -> abdominal pain
- "mi cyaan breathe good" -> dyspnoea
- "mi head a hurt mi bad" -> severe headache
- "mi pressure high" -> elevated BP (patient-reported)
- "mi sugar high" -> elevated blood glucose (patient-reported)
- "mi feel fi vomit" / "mi a vomit" -> nausea / vomiting
- "mi belly a run" -> diarrhoea
- "di pickney have fever" -> paediatric fever

CRITICAL — Patois negation and self-correction:
- "nou" in Jamaican Patois = "no" (negation / correction), NOT the English word "now".
  Do NOT interpret "nou" as a time reference.
- Pattern: "X nou Y" or "X, nou, Y" means the speaker is CORRECTING themselves —
  they first said X then rejected it and said Y. Record only the corrected value Y.
  Example: "pain level is 6 nou it's an 8 out of 10" -> pain 8/10 (patient self-corrected
  from 6 to 8; discard the 6).
- "nuh" = "no" / "not" (e.g. "mi nuh feel it" = "I don't feel it").
- "nat" / "nah" = "not" / "no" (e.g. "nah it worse" = "no, it's worse").
- "ant" = "isn't it" / affirmation tag at end of sentence; does NOT negate the statement.
- When a patient self-corrects any numerical value (pain score, BP reading, duration,
  frequency), always record the FINAL stated value, not the initial one.

CRITICAL — Uncertainty flags from the interpreter:
The transcript may contain [UNCERTAIN: ...], [SELF-CORRECTION: ...], [CONDITIONAL-not-definite: ...],
[APPROXIMATE VALUE ~X: ...], [BLOOD PRESSURE READING: ...], or [CANNOT: ...] annotations
inserted by the pre-processing layer. Rules:
- PRESERVE every [UNCERTAIN: ...] tag verbatim in the note so the clinician can see it.
  Do NOT resolve or remove uncertainty tags — they must reach the doctor.
- [SELF-CORRECTION: ...] → use only the corrected (final) value.
- [CONDITIONAL-not-definite: ...] → the symptom described is situational/hypothetical,
  NOT a definite active complaint. Mark clearly: "Patient reports situational X."
- [APPROXIMATE VALUE ~X: ...] → record as approximate, not exact.
- [BLOOD PRESSURE READING: X over Y: ...] → record as BP X/Y (verify).
- [CANNOT: ...] → the patient said they CANNOT do the described action.
"""


# ── v3: Generic context addendum ─────────────────────────────────────────────
# Used for non-Jamaican languages. Replaces JAMAICAN_CONTEXT_ADDENDUM when
# preferred_language is not jam_Latn.  No region-specific drug names, herbs,
# or dialect rules — just universal clinical documentation guidance.
GENERIC_CONTEXT_ADDENDUM = """GENERAL CLINICAL CONTEXT (apply silently when relevant):

Common encounter types: acute illness, chronic disease follow-up (hypertension,
diabetes, asthma, COPD), antenatal, paediatric, mental health, wound care,
post-operative review, preventive health.

Medication recognition: recognise both brand and generic names for common drug
classes (antihypertensives, antidiabetics, antibiotics, analgesics, inhalers,
antiretrovirals, anticoagulants). If a name is unclear, flag it:
[MEDICATION NAME UNCLEAR: transcribed as "X"] and preserve the phonetic form.

Allergy phrases to watch for — extract to Allergies field:
"allergic to X", "can't take X", "X makes me react", "X gives me a rash/swelling".
If no allergy confirmed by doctor, write NKA only if explicitly stated.

Uncertainty flags — preserve all [UNCERTAIN: ...], [SELF-CORRECTION: ...],
[CONDITIONAL-not-definite: ...], [APPROXIMATE VALUE ~X: ...],
[BLOOD PRESSURE READING: X over Y: ...], and [CANNOT: ...] annotations verbatim.
"""


# ---------------------------------------------------------------------------
# Layer 2 - User prompts (one-shot for small reasoning models)
# ---------------------------------------------------------------------------

SINGLE_SOAP_USER_PROMPT = """Convert the transcript into a comprehensive structured clinical note.

Output five labelled sections in exactly this order. Each label on its own line.
No markdown. End with the disclaimer.

SUMMARY:
<2-3 concise bullet points (use plain "- ") giving a TL;DR: who the patient is,
why they came, and the key action taken. Busy clinicians read this first.
Only include what is in the transcript.>

S:
<Subjective — use these sub-labels on their own lines, include only what
the transcript covers, omit sub-labels that have no content:

CC: <chief complaint in one clinical English sentence — do NOT quote patient
in dialect/patois; translate to standard clinical language>
HPI: <history of present illness — write as a flowing clinical narrative (2-4
sentences). Weave together onset, duration, character, severity, associated
symptoms, and aggravating/relieving factors into prose. Only break into bullets
if there are 5 or more genuinely independent elements that cannot flow together.>
PMH: <past medical / surgical history if stated>
Family History: <only if stated>
Social History: <smoking, alcohol, occupation, herbal remedies if stated>
Current Medications: <list; one entry per line, indented:
  • Drug Dose Route Frequency>
Allergies: <drug allergies; write NKA if doctor confirmed none>
ROS: <review of systems not already covered in HPI, only if stated>>

O:
<Objective — use these sub-labels, omit any that have no data:

Vitals: <BP / HR / RR / T / SpO2 / Wt / Ht / BMI / Glucose. Write only the
values the doctor stated. If a vital was mentioned as abnormal but the exact
value was NOT stated, write it as [value not stated] so the doctor can fill
it in — e.g. "BP [value not stated] — elevated per doctor".>
Examination: <general appearance first, then system findings as INDENTED bullets:
  • CVS: ...
  • Respiratory: ...
Omit any system not mentioned.>
Investigations: <lab results, imaging, ECG — only values the doctor stated>>

A:
<Assessment — number each problem or diagnosis. After each number write the
clinical impression in the doctor's words, with status in parentheses if stated
(controlled / uncontrolled / stable / worsening / new onset). Then append the
ICD-10 code in parentheses, e.g. "(ICD-10 I10)". Code ONLY a condition the doctor
actually diagnosed or confirmed — NEVER one the patient merely mentioned, denied,
or that belongs to family history. If you are not confident of the exact code,
write "(ICD-10 ?)" so the clinician completes it. Flag critical findings with
[ALERT]. Do NOT add "rule out", "evaluate for", or differentials unless the doctor
explicitly said them.>

P:
<Plan — number to match assessment. Under each number use INDENTED sub-groups:
  - Medications: Drug Dose Route Frequency x Duration (write [dose not stated]
    if dose not given; NEVER fabricate)
  - Investigations: tests ordered
  - Referrals: if stated
  - Education: advice given to patient
  - Follow-up: timing if stated
Omit any sub-category that has no content. Do NOT add items the doctor did not state.>

AI-generated draft - review and edit required before clinical use.

EXAMPLE OUTPUT (abbreviated):

SUMMARY:
- 58 y/o female, routine hypertension follow-up.
- BP suboptimally controlled on current regimen.
- Amlodipine dose increased; BP recheck in 2 weeks.

S:
CC: Routine hypertension follow-up.
HPI: Patient reports home BP was elevated last week. Denies chest pain, SOB, or headache.
Current Medications: Amlodipine 5mg PO OD.
Allergies: NKA.

O:
Vitals: BP 138/86 mmHg | HR 72 bpm | RR 16.
Examination: Not documented.

A:
1. Hypertension (uncontrolled) — target BP not achieved on current regimen. (ICD-10 I10)

P:
1. Hypertension
   - Medications: Amlodipine 10mg PO OD x 30 days
   - Follow-up: BP recheck in 2 weeks
   - Education: Continue low-salt diet.

AI-generated draft - review and edit required before clinical use.

DOCTOR CONTEXT: specialty = {specialty}; preferred style = {note_style};
length mode = {length_mode}.

TRANSCRIPT:
{transcript}
"""


SINGLE_SOAP_USER_PROMPT_SUGGESTIVE = """Convert the transcript into a comprehensive structured clinical note.

Output five labelled sections in exactly this order. Each label on its own line.
No markdown. End with the disclaimer.

SUMMARY:
<2-3 concise bullet points (use plain "- ") giving a TL;DR: who the patient is,
why they came, and the key action taken. Busy clinicians read this first.
Only include what is in the transcript.>

S:
<Subjective — use these sub-labels on their own lines, include only what
the transcript covers, omit sub-labels that have no content:

CC: <chief complaint in one clinical English sentence — do NOT quote patient
in dialect/patois; translate to standard clinical language>
HPI: <history of present illness — write as a flowing clinical narrative (2-4
sentences). Weave together onset, duration, character, severity, associated
symptoms, and aggravating/relieving factors into prose. Only break into bullets
if there are 5 or more genuinely independent elements that cannot flow together.>
PMH: <past medical / surgical history if stated>
Family History: <only if stated>
Social History: <smoking, alcohol, occupation, herbal remedies if stated>
Current Medications: <list; one entry per line, indented:
  • Drug Dose Route Frequency>
Allergies: <drug allergies; write NKA if doctor confirmed none>
ROS: <review of systems not already covered in HPI, only if stated>>

O:
<Objective — use these sub-labels, omit any that have no data:

Vitals: <BP / HR / RR / T / SpO2 / Wt / Ht / BMI / Glucose. Write only the
values the doctor stated. If a vital was mentioned as abnormal but the exact
value was NOT stated, write it as [value not stated] so the doctor can fill
it in — e.g. "BP [value not stated] — elevated per doctor".>
Examination: <general appearance first, then system findings as INDENTED bullets:
  • CVS: ...
  • Respiratory: ...
Omit any system not mentioned.>
Investigations: <lab results, imaging, ECG — only values the doctor stated>>

A:
<Assessment — number each problem. Include status in parentheses if stated.
Then append the ICD-10 code in parentheses, e.g. "(ICD-10 I10)". Code ONLY a
condition the doctor actually diagnosed or confirmed — NEVER one the patient
merely mentioned, denied, or that belongs to family history. If unsure of the
exact code, write "(ICD-10 ?)". Flag critical findings with [ALERT]. When strongly
implied by the transcript, you may add concise provisional "rule out", "consider",
or "possible" wording.>

P:
<Plan — number to match assessment. Under each number group:
- Medications: Drug Dose Route Frequency x Duration (write [dose not stated]
  if dose not given; NEVER fabricate)
- Investigations: tests ordered; when strongly implied, you may suggest generic workup
- Referrals: if stated
- Education: advice given to patient
- Follow-up: timing if stated
Omit any sub-category that has no content.>

AI-generated draft - review and edit required before clinical use.

EXAMPLE OUTPUT (abbreviated):

SUMMARY:
- 58 y/o female, routine hypertension follow-up.
- BP suboptimally controlled on current regimen.
- Amlodipine dose increased; BP recheck in 2 weeks.

S:
CC: Routine hypertension follow-up.
HPI: Patient reports home BP was elevated last week. Denies chest pain, SOB, or headache.
Current Medications: Amlodipine 5mg PO OD.
Allergies: NKA.

O:
Vitals: BP 138/86 mmHg | HR 72 bpm | RR 16.
Examination: Not documented.

A:
1. Hypertension (uncontrolled) — target BP not achieved; consider metabolic panel to rule out secondary causes. (ICD-10 I10)

P:
1. Hypertension
   - Medications: Amlodipine 10mg PO OD x 30 days
   - Investigations: U&E, renal function in 4 weeks
   - Follow-up: BP recheck in 2 weeks
   - Education: Continue low-salt diet, weight reduction.

AI-generated draft - review and edit required before clinical use.

DOCTOR CONTEXT: specialty = {specialty}; preferred style = {note_style};
length mode = {length_mode}.

TRANSCRIPT:
{transcript}
"""


NARRATIVE_USER_PROMPT = """Write a narrative-style clinical note from the
transcript. Free-flowing prose, one to three short paragraphs. Cover (in
order): why the patient came in, relevant history, what was found on
examination, the doctor's assessment, the plan.

Stay strictly faithful to what was said. Do not invent. End with:
"AI-generated draft - review and edit required before clinical use."

DOCTOR CONTEXT: specialty = {specialty}; length mode = {length_mode}.

TRANSCRIPT:
{transcript}
"""


CHART_USER_PROMPT = """Write a chart-style progress note from the transcript.

Use these labels, each on its own line. OMIT any line that has no
corresponding data (do not write "Not documented" for individual lines).

Date/Time: <only if stated>
Reason for visit:
Subjective:
Objective:
Assessment:
Plan:
Follow-up:

End with: AI-generated draft - review and edit required before clinical use.

DOCTOR CONTEXT: specialty = {specialty}; length mode = {length_mode}.

TRANSCRIPT:
{transcript}
"""


# ---------------------------------------------------------------------------
# Layer 2b - Modular section prompts (for SCRIBE_PIPELINE_MODE=modular)
# ---------------------------------------------------------------------------

SECTION_PROMPTS = {
    "subjective": """Write ONLY the Subjective (S) section.

Use these sub-labels on their own lines. Include ONLY what the transcript
covers; omit any sub-label that has no content.

CC: <chief complaint>
HPI: <onset, duration, character, severity, radiation, aggravating/relieving, associated symptoms>
PMH: <past medical/surgical history if stated>
Family History: <only if stated>
Social History: <smoking, alcohol, occupation, herbal remedies if stated>
Current Medications: <each drug, dose, route, frequency if stated>
Allergies: <allergies; write NKA if confirmed none>
ROS: <review of systems not already in HPI, only if stated>

Output starts with "S:" on its own line. If absolutely nothing relevant is
in the transcript, write: S:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
    "objective": """Write ONLY the Objective (O) section.

Use these sub-labels on their own lines. Include ONLY what the doctor stated;
omit any sub-label that has no data.

Vitals: <BP / HR / RR / T / SpO2 / Wt / Ht / BMI / Glucose — stated values only>
Examination: <general appearance then system findings as stated>
Investigations: <lab results, imaging, ECG — only stated values>

Output starts with "O:" on its own line. If nothing objective was
documented, write: O:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
    "assessment": """Write ONLY the Assessment (A) section.

Number diagnoses or clinical impressions in the doctor's words. Preserve
clinical uncertainty ("Likely X" stays "Likely X"). Add status in
parentheses if stated. Do NOT add "rule out", "evaluate for", or
differential suggestions unless the doctor explicitly said them.

Output starts with "A:" on its own line. If no assessment was discussed,
write: A:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
    "plan": """Write ONLY the Plan (P) section.

Number items to match assessment numbers when possible. Medications:
"Drug Xmg ROUTE FREQ x DURATION". If no dose was stated, write
"[dose not stated]". Never fabricate a dose. Do NOT add tests, workup,
referrals, or follow-up suggestions unless the doctor explicitly stated them.

Output starts with "P:" on its own line. If no plan was discussed,
write: P:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
}


SECTION_PROMPTS_SUGGESTIVE = {
    **SECTION_PROMPTS,
    "assessment": """Write ONLY the Assessment (A) section.

Number diagnoses or clinical impressions in the doctor's words. Preserve
clinical uncertainty ("Likely X" stays "Likely X"). Add status in
parentheses if stated. When strongly implied by the transcript, you may add
concise provisional wording such as "possible", "consider", or "rule out".

Output starts with "A:" on its own line. If no assessment was discussed,
write: A:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
    "plan": """Write ONLY the Plan (P) section.

Number items to match assessment numbers when possible. Medications:
"Drug Xmg ROUTE FREQ x DURATION". If no dose was stated, write
"[dose not stated]". Never fabricate a dose. When strongly implied by the
transcript, you may add concise generic next-step / workup suggestions.

Output starts with "P:" on its own line. If no plan was discussed,
write: P:\\nNot documented.

TRANSCRIPT:
{transcript}
""",
}


# ---------------------------------------------------------------------------
# Layer 3 - Verifier
# ---------------------------------------------------------------------------

VERIFICATION_PROMPT = """Compare the generated SOAP section against the
transcript. Flag only:
- [HALLUCINATION] anything in the section NOT present in the transcript
- [OMISSION] clinically critical info in the transcript that was missed
  (medications, doses, diagnoses, critical findings, herbs)

Do not flag style or formatting. Do not suggest additions the transcript
doesn't support.

TRANSCRIPT:
{transcript}

GENERATED SECTION ({section_name}):
{generated_section}

Reply EITHER:
VERIFIED - No issues found.

OR:
ISSUES FOUND:
- [HALLUCINATION] "<line>" - Not present in transcript.
- [OMISSION] "<what was missed>" - Present in transcript but not in note.

CORRECTED SECTION:
<full corrected section here>
"""


# ---------------------------------------------------------------------------
# Specialty addenda
# ---------------------------------------------------------------------------

def specialty_addendum(specialty: str) -> str:
    bits = {
        "anesthesia": (
            "ANESTHESIOLOGY: prioritise pre-op assessment (ASA class, airway, "
            "allergies, last meal), intra-op events, anaesthetic agents and "
            "doses given, vitals trends, recovery notes."
        ),
        "obgyn": (
            "OB/GYN: capture LMP, gestational age, gravida/para, fundal height, "
            "fetal heart rate, fetal movement when stated. Methyldopa is "
            "first-line antihypertensive in pregnancy in Jamaica."
        ),
        "pediatrics": (
            "PAEDIATRICS: child's age and weight, informant relationship if "
            "stated, immunisation status if mentioned. Do not flag paediatric "
            "vitals as abnormal using adult thresholds."
        ),
        "psychiatry": (
            "PSYCHIATRY: capture mood/affect, thought content, suicide/homicide "
            "ideation, insight/judgment as stated. Mental state exam bullets "
            "only when verbalised."
        ),
        "neurology": (
            "NEUROLOGY: capture cranial nerves, motor/sensory exam, reflexes, "
            "gait, cognition only as stated. Document focal deficits verbatim."
        ),
        "cardiology": (
            "CARDIOLOGY: capture chest pain characteristics, NYHA class, ECG "
            "findings, echo findings, troponin levels only as stated."
        ),
        "surgery": (
            "SURGERY: capture procedure performed, indication, findings, "
            "complications, post-op orders only as stated."
        ),
        "emergency": (
            "EMERGENCY MEDICINE: triage category, time of arrival, interventions "
            "performed, disposition (admit/discharge/transfer)."
        ),
    }
    return bits.get(specialty, "")


# ---------------------------------------------------------------------------
# Suggest improvements
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Demographics + vitals extraction (Triage conversation-mode panel)
# ---------------------------------------------------------------------------
# Returns a strict JSON object with patient and encounter facts. Used to
# pre-fill an editable form so the doctor can verify/correct what the AI heard.
# Nothing is persisted — the form is a sanity check on the transcript only.

DEMOGRAPHICS_EXTRACTION_PROMPT = """You are a clinical data extractor. Read
the clinical English transcript below and return a SINGLE JSON object with the
patient and encounter facts present.

CRITICAL RULES:
1. EXTRACT, DON'T INVENT. If a field is not stated in the transcript, return
   an empty string "" (or empty list for lists). Never guess.
2. Output ONLY the JSON object. No prose, no markdown fences, no commentary.
3. Use exact units as stated by the doctor. If a unit is ambiguous, leave
   the value as the doctor said it (e.g. "120" rather than "120 mmHg").

OUTPUT SCHEMA (return EVERY key, with "" / [] when absent):

{{
  "patient": {{
    "name": "",
    "age": "",
    "dob": "",
    "sex": "",
    "id_or_record_number": ""
  }},
  "vitals": {{
    "bp": "",
    "hr": "",
    "temp": "",
    "rr": "",
    "spo2": "",
    "weight": "",
    "height": "",
    "bmi": "",
    "glucose": ""
  }},
  "allergies": [],
  "current_medications": [],
  "chief_complaint": "",
  "history_summary": ""
}}

TRANSCRIPT:
{transcript}
"""


# ---------------------------------------------------------------------------
# Drug interaction checker (Jamaican context)
# ---------------------------------------------------------------------------
# Notes on safety design (Dr Adrian feedback):
#   - We pre-resolve brand → generic + drug_class via the DrugAlias table
#     BEFORE the AI call. The AI never sees raw brand names, so it can't
#     hallucinate that "Vita-Cax" is something unrelated.
#   - The AI must label every finding with severity + confidence + mechanism.
#     Low-confidence findings are surfaced as advisories, not directives.
#   - We require the AI to flag an *unresolved* drug (when the alias table
#     didn't resolve and the AI can't confidently identify it) rather than
#     guess — see UNRECOGNIZED handling in the schema.
#   - Output is strict JSON so the UI can render without parsing prose.

DRUG_INTERACTION_PROMPT = """You are a clinical pharmacology assistant for a
Jamaican-Caribbean medical scribe. The doctor has supplied:
- Current medications the patient is already on
- Optional bush teas / herbal remedies the patient uses
- A PROPOSED medication the doctor is considering adding
- Optional patient context (age, sex, conditions, allergies)

Every drug has been pre-resolved (where possible) to its generic name and
drug class. Items marked UNRECOGNIZED could not be resolved — treat them with
caution: if you do not confidently know the substance, say so in the
"unrecognized" array rather than guessing.

YOUR JOB:
Identify clinically relevant interactions between the PROPOSED medication and:
  (a) each current medication
  (b) each herbal remedy
  (c) the patient's listed conditions / allergies / age
Also flag duplications (same drug class already on board), contraindications,
and dosage considerations.

OUTPUT — return a SINGLE JSON object. No prose outside the JSON. No markdown.

SCHEMA (return every key; use [] / "" / null for absent values):

{{
  "summary": "1-2 sentence headline for the doctor (plain English).",
  "overall_severity": "critical | major | moderate | minor | none",
  "findings": [
    {{
      "type": "interaction | duplication | contraindication | dosing | monitoring",
      "severity": "critical | major | moderate | minor",
      "confidence": "high | medium | low",
      "involves": ["<generic name A>", "<generic name B or condition>"],
      "mechanism": "1-2 sentence explanation a GP would understand.",
      "clinical_effect": "What actually happens to the patient.",
      "recommendation": "What the doctor could do (alternative, monitor, dose-adjust, avoid).",
      "alternatives": ["<safer generic option>"],
      "evidence_strength": "well-established | reported | theoretical"
    }}
  ],
  "unrecognized": [
    {{
      "input": "<exactly what the doctor typed>",
      "reason": "Why you could not confidently identify it.",
      "ask_doctor": "What clarification would help."
    }}
  ],
  "disclaimer": "AI advisory only — not a substitute for clinical judgment. Always cross-check with a current drug reference."
}}

RULES:
1. Only report findings you can defend pharmacologically. If unsure: confidence=low or move to "unrecognized".
2. Do NOT invent dose numbers. If a dose adjustment is needed, say "consider dose reduction" — never quote a specific mg figure unless the doctor supplied one.
3. Herb interactions: be honest about evidence_strength — most herb/drug data is "reported" at best.
4. If there are no clinically relevant issues, return an empty findings array, overall_severity="none", and summary saying so.
5. Critical/major severity must include a clear recommendation.

INPUT:
{payload}
"""


IMPROVE_PROMPT = """Read the note and list 3 to 6 specific, actionable
improvements. Focus on:
- Missing fields a clinician would expect (e.g. vitals, plan timing)
- Grammar / clarity issues
- Inconsistent abbreviations or units
- Any [unclear] or "Not documented" entries the doctor should resolve

Be concise. Do NOT invent clinical facts. Do NOT recommend specific
diagnoses or doses. Output bullets prefixed with "- ".

NOTE:
{note}
"""
