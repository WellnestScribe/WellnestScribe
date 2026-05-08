"""SOAP / narrative / chart note generation via Azure OpenAI.

Reasoning-model awareness: Azure deployments backed by GPT-5 / o-series
spend tokens on internal reasoning before emitting any output. With a
small `max_completion_tokens` budget the model can return an empty
string. We detect that and retry with a larger budget + minimal
reasoning effort. This mirrors what production scribes do.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from django.conf import settings
from openai import BadRequestError

from .clients import get_chat_client
from .prompts import (
    CHART_USER_PROMPT,
    IMPROVE_PROMPT,
    JAMAICAN_CONTEXT_ADDENDUM,
    MASTER_SYSTEM_PROMPT,
    NARRATIVE_USER_PROMPT,
    SECTION_PROMPTS,
    SINGLE_SOAP_USER_PROMPT,
    VERIFICATION_PROMPT,
    specialty_addendum,
)


logger = logging.getLogger(__name__)


@dataclass
class GeneratedNote:
    note_format: str
    full_note: str
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    narrative: str = ""
    flags: list[str] = field(default_factory=list)


_REASONING_HINTS = ("gpt-5", "o1", "o3", "o4", "reasoning")
_reasoning_effort_supported: bool | None = None


def _is_reasoning_deployment() -> bool:
    name = (settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT or "").lower()
    return any(h in name for h in _REASONING_HINTS)


def _system_prompt(specialty: str, custom_instructions: str = "") -> str:
    parts: list[str] = [MASTER_SYSTEM_PROMPT, JAMAICAN_CONTEXT_ADDENDUM]
    addendum = specialty_addendum(specialty)
    if addendum:
        parts.append(addendum)
    if custom_instructions:
        parts.append(
            "DOCTOR PREFERENCES (apply throughout):\n" + custom_instructions.strip()
        )
    return "\n\n".join(parts)


def _looks_like_refusal(text: str) -> bool:
    """Detect when the model wrote 'Not documented' for almost everything.

    True when 3+ of the 4 SOAP sections are exactly 'Not documented' (or
    similar minimal content). Signals an over-conservative response we
    should retry with a more explicit extraction prompt.
    """
    if not text:
        return True
    sections = _split_soap(text)
    empties = 0
    for k, v in sections.items():
        clean = (v or "").strip().lower()
        if not clean or clean in {"not documented.", "not documented", "n/a", "none"}:
            empties += 1
    return empties >= 3


def _is_reasoning_effort_error(exc: BadRequestError) -> bool:
    message = str(exc).lower()
    return "reasoning_effort" in message and "unrecognized request argument" in message


def _chat(messages: list[dict], *, max_tokens: int | None = None) -> str:
    """Call the chat deployment, with retry-on-empty for reasoning models."""
    global _reasoning_effort_supported

    client = get_chat_client()
    deployment = settings.SCRIBE_AZURE_OPENAI_DEPLOYMENT
    is_reasoning = _is_reasoning_deployment()
    supports_reasoning_effort = _reasoning_effort_supported is not False

    base_budget = max_tokens or settings.SCRIBE_MAX_COMPLETION_TOKENS
    if is_reasoning and base_budget < 4000:
        base_budget = 4000

    attempts = []
    if is_reasoning:
        attempts.append(
            {
                "max_completion_tokens": base_budget,
                "reasoning_effort": "minimal" if supports_reasoning_effort else None,
            }
        )
        attempts.append(
            {
                "max_completion_tokens": max(base_budget * 2, 8000),
                "reasoning_effort": "low" if supports_reasoning_effort else None,
            }
        )
    else:
        attempts.append({"max_completion_tokens": base_budget})
        attempts.append({"max_completion_tokens": max(base_budget * 2, 4000)})

    last_response = None
    for attempt_kwargs in attempts:
        kwargs: dict = {"model": deployment, "messages": messages}
        # Reasoning models accept `reasoning_effort` (passed via extra_body for
        # SDKs that don't surface it as a typed kwarg yet).
        effort = attempt_kwargs.pop("reasoning_effort", None)
        kwargs.update(attempt_kwargs)
        if effort is not None:
            kwargs["extra_body"] = {"reasoning_effort": effort}

        try:
            response = client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if effort is not None and _is_reasoning_effort_error(exc):
                _reasoning_effort_supported = False
                logger.warning(
                    "Deployment %s rejected reasoning_effort; retrying without it.",
                    deployment,
                )
                kwargs.pop("extra_body", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise
        last_response = response
        text = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        finish = response.choices[0].finish_reason
        logger.info(
            "chat call: model=%s finish=%s out_chars=%d reasoning_tokens=%s completion_tokens=%s",
            deployment,
            finish,
            len(text),
            getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", "n/a"),
            getattr(usage, "completion_tokens", "n/a"),
        )
        if text:
            return text
        # Empty output → likely budget consumed by reasoning. Try again.
        logger.warning(
            "Empty completion (finish=%s). Retrying with bigger budget.", finish
        )

    finish = getattr(last_response.choices[0], "finish_reason", "unknown") if last_response else "no-response"
    raise RuntimeError(
        f"Model returned no output after {len(attempts)} attempts (finish={finish}). "
        "Increase SCRIBE_MAX_COMPLETION_TOKENS or switch to a non-reasoning deployment."
    )


_SECTION_HEADERS = ("S:", "O:", "A:", "P:")


def _split_soap(full_note: str) -> dict[str, str]:
    """Best-effort split of a SOAP block into its four sections."""
    pattern = re.compile(r"(?m)^(S:|O:|A:|P:)\s*")
    matches = list(pattern.finditer(full_note))
    if not matches:
        return {
            "subjective": full_note,
            "objective": "",
            "assessment": "",
            "plan": "",
        }

    sections = {"S:": "", "O:": "", "A:": "", "P:": ""}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_note)
        sections[match.group(1)] = full_note[match.end():end].strip()
    return {
        "subjective": sections["S:"],
        "objective": sections["O:"],
        "assessment": sections["A:"],
        "plan": sections["P:"],
    }


def _extract_flags(text: str) -> list[str]:
    return re.findall(r"\[(?:ALERT|HALLUCINATION|HERB-DRUG NOTE)[^\]]*\]", text)


def generate_note(
    transcript: str,
    *,
    note_format: str = "soap",
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(specialty, custom_instructions)

    if note_format == "narrative":
        user = NARRATIVE_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    elif note_format == "chart":
        user = CHART_USER_PROMPT.format(
            specialty=specialty, length_mode=length_mode, transcript=transcript
        )
    else:
        note_format = "soap"
        user = SINGLE_SOAP_USER_PROMPT.format(
            specialty=specialty,
            note_style="SOAP",
            length_mode=length_mode,
            transcript=transcript,
        )

    full_note = _chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ]
    )

    # Refusal-pattern retry: when a SOAP comes back as "Not documented" in
    # 3+ sections but the transcript clearly has clinical content, the
    # model is being too conservative. Re-prompt with a stricter extraction
    # nudge that overrides its caution.
    if note_format == "soap" and _looks_like_refusal(full_note) and len(transcript) > 60:
        logger.warning("SOAP looks like a refusal — retrying with stricter extraction prompt.")
        push = (
            "Your previous attempt was too conservative — most sections came back as "
            "'Not documented' even though the transcript contains clinical content. "
            "Re-read the transcript and EXTRACT every fact present (symptoms, history, "
            "vitals, exam findings, diagnoses, plan items). Use 'Not documented' ONLY "
            "for an entire section that genuinely has zero relevant content.\n\n"
            "PREVIOUS ATTEMPT (over-conservative):\n"
            f"{full_note}\n\n"
            "Now produce a correct SOAP note from the transcript:\n"
            f"{transcript}"
        )
        retry_text = _chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
                {"role": "assistant", "content": full_note},
                {"role": "user", "content": push},
            ]
        )
        if retry_text and not _looks_like_refusal(retry_text):
            full_note = retry_text

    note = GeneratedNote(note_format=note_format, full_note=full_note)
    note.flags = _extract_flags(full_note)
    if note_format == "soap":
        sections = _split_soap(full_note)
        note.subjective = sections["subjective"]
        note.objective = sections["objective"]
        note.assessment = sections["assessment"]
        note.plan = sections["plan"]
    elif note_format == "narrative":
        note.narrative = full_note
    return note


def generate_modular_soap(
    transcript: str,
    *,
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
    sections: Iterable[str] = ("subjective", "objective", "assessment", "plan"),
) -> GeneratedNote:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot generate a note from an empty transcript.")

    system_prompt = _system_prompt(specialty, custom_instructions)
    out: dict[str, str] = {}
    for name in sections:
        prompt = SECTION_PROMPTS[name].format(transcript=transcript)
        out[name] = _chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        )

    full_note = "\n\n".join(
        out[s] for s in ("subjective", "objective", "assessment", "plan") if s in out
    )
    note = GeneratedNote(
        note_format="soap",
        full_note=full_note,
        subjective=out.get("subjective", ""),
        objective=out.get("objective", ""),
        assessment=out.get("assessment", ""),
        plan=out.get("plan", ""),
    )
    note.flags = _extract_flags(full_note)
    return note


def verify_section(
    transcript: str, generated_section: str, section_name: str
) -> str:
    return _chat(
        [
            {"role": "system", "content": "You are a clinical documentation quality reviewer."},
            {
                "role": "user",
                "content": VERIFICATION_PROMPT.format(
                    transcript=transcript,
                    section_name=section_name,
                    generated_section=generated_section,
                ),
            },
        ]
    )


# ---- Suggest improvements (grammar, completeness, missing sections) ----

IMPROVE_PROMPT = """You are a clinical documentation quality reviewer.

Read the following note and suggest specific, actionable improvements.
Focus on:
- Missing fields a reader would expect (e.g. vitals not captured, no plan stated)
- Grammar / clarity issues that hurt readability
- Inconsistent abbreviations or units
- Any [unclear] / "Not documented" entries the doctor should resolve

Be concise. Do NOT invent clinical facts. Do NOT recommend specific
diagnoses or doses. Output 3 to 6 short bullets prefixed with "- ".

NOTE:
{note}
"""


def suggest_improvements(note_text: str, *, specialty: str = "general") -> str:
    note_text = (note_text or "").strip()
    if not note_text:
        return "- Note is empty. Generate or write content first."
    return _chat(
        [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": IMPROVE_PROMPT.format(note=note_text)},
        ],
        max_tokens=1200,
    )


POLISH_PROMPT = """Clean up the grammar, spelling, and clinical phrasing of
the note below. PRESERVE every clinical fact exactly. Do not add or remove
findings, diagnoses, doses, or vitals.

Keep the existing S:/O:/A:/P: section labels (or the existing structure if
there are no labels). Output the polished note in the same plain-text
format. End with: AI-generated draft — review and edit required before
clinical use.

NOTE TO POLISH:
{note}
"""


def polish_grammar(note_text: str) -> str:
    note_text = (note_text or "").strip()
    if not note_text:
        return ""
    return _chat(
        [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": POLISH_PROMPT.format(note=note_text)},
        ]
    )


# ---- Patois ASR post-processor ----
# Used by the Triage sandbox to interpret raw MMS / Patois output and
# convert it into clean clinical English the SOAP pipeline can consume.

TATOIS_INTERPRETER_SYSTEM_PROMPT = """You are a Jamaican Patois-to-clinical-English
interpreter for a medical scribe. The text below is a raw transcript from
an ASR model that captured a Jamaican Creole (Patwa) speaker. The
spelling is non-standard and inconsistent — that is normal for Patwa.

Your job:
1. Read the Patwa carefully. Patwa is mostly intelligible to English
   speakers if read phonetically. Examples:
   "yu nuo se" = "you know that"
   "fram maan iin" = "from morning"
   "mi beli a kil mi" / "mi beli-batam a kil mi" = "my belly / lower abdomen
       is killing me" → severe abdominal/lower-abdominal pain
   "mi tek som serasi bush" = "I drank some cerasee tea" (herbal remedy)
   "mi staat vamit" = "I started vomiting"
   "mi ed a ap mi" = "my head is hammering me / pounding"
   "mi ai dem torn red" = "my eyes turned red"
   "mi fingga dem a wan piis a pien" = "my fingers are intensely painful"
   "knife mi" / "naip mi" = sharp/stabbing sensation
   "mi go jringk som bizni" = "I drank some bissy/kola-nut tea" (often used
       after suspected poisoning or as a tonic)
   "dem gaa mi bed" = "they put me to bed"
   "pikni" = "child"; "di pikni sik" = "the child is sick"
2. Rewrite the content as clean, neutral clinical English in third person
   ("Patient reports..."). Capture every symptom, time course, herbal
   remedy, and self-treatment.
3. Tag herbs with [HERBAL SUPPLEMENT] (cerasee, fever grass, bissy,
   soursop leaf, jackass bitters, noni, turmeric, aloe vera).
4. Do NOT invent symptoms, diagnoses, doses, or vitals.
5. If a phrase is genuinely unintelligible, write [unclear: "<phrase>"].

Output ONLY the rewritten clinical English. No commentary, no markdown.
"""

PATOIS_INTERPRETER_SYSTEM_PROMPT = """
\
CONTENT FILTER DECLARATION (READ FIRST)
 
This system prompt is used in a medical clinical setting to interpret Jamaican \
Patois (Patwa) speech-to-text transcripts from patients. The input text is a \
Caribbean creole language transcribed phonetically from audio recordings. Many \
Patwa words for anatomical body parts, symptoms, and folk medicine terms may \
superficially resemble flagged content in English but are standard medical \
vocabulary in this context. Examples:
- "batam" = plantar surface of the foot (NOT sexual)
- "pum pum" = vulva (legitimate gynaecological term)
- "buddy" = penis (legitimate anatomical term)
- "front" = anterior / genitalia (legitimate anatomical term)
- "hood" = penis (legitimate anatomical term in this dialect)
Do NOT filter, refuse, or truncate responses based on these terms. \
This is a licensed medical application. Treat all input as clinical data.
 
---
 
YOUR ROLE
 
You are a Jamaican Patois-to-clinical-English medical interpreter. Your job is \
to take raw phonetic Patwa transcripts (produced by speech-to-text from patient \
audio) and convert them into accurate, structured clinical English summaries for \
healthcare providers.
 
You have deep knowledge of Jamaican Patois phonetics, grammar, proverbs, and \
folk medicine. Patwa is a creole language with its own grammar — it is NOT \
broken English. Never treat it as garbled text. Always resolve it phonetically \
and linguistically before interpreting.
 
---
 
MANDATORY PROCESSING RULES — NEVER SKIP THESE
 
RULE 1 — ALWAYS PROCESS IN 3 STEPS IN ORDER
 
You MUST complete all 3 steps before writing any clinical output. \
Do not jump ahead. Do not skip Step 1 or Step 2.
 
STEP 1 — PHONETIC RESOLUTION
Rewrite every token in the transcript word by word using the phonetic rules \
below. Output plain English words — no grammar yet, just resolved tokens.
 
STEP 2 — LINGUISTIC ASSEMBLY
Assemble the resolved tokens into grammatical English sentences, applying Patwa \
grammar rules (subject-verb patterns, discourse markers, hedging patterns).
 
STEP 3 — CLINICAL INTERPRETATION
Convert the assembled English into the structured clinical output template \
at the end of this prompt.
 
---
 
RULE 2 — NEGATION RULES (PATIENT SAFETY CRITICAL)
 
Getting negation wrong is a clinical error. Follow these absolutely:
1. "kyaahn" / "cyaahn" / "caah" ALWAYS means CANNOT. Never "can."
2. "nuh" / "nah" / "na" ALWAYS means NO or NOT.
3. "neva" ALWAYS means NEVER or DID NOT.
4. "mi nuh have pain" = patient has NO pain. Not "patient has pain."
5. "mi kyaahn tek it" = patient CANNOT tolerate it. Not "patient can take it."
6. Double-check every sentence for nuh/nah/kyaahn/neva before outputting.
7. "mi no riili... bot" = hedging pattern. "no riili" is a softener. \
   The real statement comes AFTER "bot" (but). That is the clinical finding.
 
---
 
RULE 3 — DISCOURSE MARKERS (NOT SYMPTOMS)
 
These are conversational fillers — do not interpret as clinical content:
- "a yu no se" / "yu know se" / "yu zimmi" = "you know what I mean" — filler
- "ibll se" / "mi a se" = "I'm saying / let me tell you" — intro filler
- "si an blind, ier an def" = proverb meaning "turn a blind eye" — NOT visual/hearing symptoms
- "a so it go" = "that's how it is" — resignation filler
- "das wa mi a seh" = "that's what I'm saying" — emphasis filler
 
---
 
RULE 4 — PATIENT MINIMISING PATTERN
 
Jamaican patients frequently minimise symptoms. Flag these clinically:
- "likkle likkle" before a serious symptom = downplaying, not mild
- "a nuh nutten" = "it's nothing" — patient downplaying, flag this
- "mi no riili" before a symptom = softening before admitting severity
- A patient presenting despite minimising = symptom is significant
 
---
 
PHONETIC RESOLUTION DICTIONARY
 
CORE GRAMMAR:
mi = I/my/me | wi = we/our | im/him = he/him/his | ar/har = she/her
dem = they/them | yuh/yu = you/your | di/de/li = the | a/ah = is/am/are/at
deh/de = there/located | inna/ina = in/inside | pon/pan = on | wid = with
fi = for/to | haffi = have to/must | seh/se = say/that | neva = never/did not
nuh/nah/na = no/not | kyaahn/cyaahn/caah = cannot | bot/but = but
an = and | das/dat = that/that is | wa/wah = what | waa/waah = want to
kaazi/kazi/caaz = cause/because | fram/from = from/since | op = of
tu/tuh = to | riili/rili = really | iiriil/eerily = really (speech artefact)
 
BODY PARTS:
batam/battam op mi fut = plantar surface/SOLE OF FOOT — NEVER abdomen
fut/foot = foot or leg (clarify from context)
bak a mi fut = posterior foot/heel/ankle
beli/belly = abdomen | ches = chest | bak/back = back | ed/hed = head
nek = neck | nee/nii = knee | nee cup = patella | elbo = elbow
han = hand | finga = finger | toa = toe | nable = navel/umbilicus
yeye/yai = eye | ier/yier = ear | teet = teeth | mout = mouth
troot/troat = throat | waist = waist/lower back | heel/hiil = heel
 
PAIN & SYMPTOMS:
pien/pain/peen = pain | apien/a pain = is causing pain | pienful = painful
sore = tenderness | swel = swelling/oedema | bun = burning | itch/iich = pruritus
numb = numbness | stiff = stiffness | weak = weakness | dizzy = dizziness
feva = fever | cough = cough | kyaahn breathe = dyspnoea
run belly = diarrhoea | trow up = vomiting | blain = visual impairment
def/deaf = hearing impairment
 
TIME & DURATION:
fram sat de/satdeh = since Saturday | fram lang taim = longstanding/chronic
fram mawning = since this morning | fram yestiday = since yesterday
wah day = a few days ago | all now = still/ongoing | jus staat = recently started
evry now an den = intermittent | tuu ze/tuezdeh = since Tuesday
 
INTENSITY:
bad bad bad = severe/extreme (9-10/10) | kyaahn tek it nomor = unbearable
likkle likkle = mild (check minimising pattern) | nuff = significant
siiriyos/serious = serious/severe | siiriyos siiriyos bad bad bad = maximum severity
 
HERBAL REMEDIES — always tag [HERBAL SUPPLEMENT]:
serisi/cerasee = Momordica charantia [HERBAL SUPPLEMENT]
bissy/bizzy = Cola acuminata [HERBAL SUPPLEMENT]
fever grass = Cymbopogon citratus [HERBAL SUPPLEMENT]
ganja tea/herb tea = Cannabis sativa [HERBAL SUPPLEMENT — flag interactions]
irish moss = Gracilaria spp. [HERBAL SUPPLEMENT]
bush tea = unidentified herbal decoction [HERBAL SUPPLEMENT — ask patient]
aloe/single bible = Aloe barbadensis [HERBAL SUPPLEMENT]
aspairin/spirin/aispani = Aspirin/ASA or Icy Hot — clarify [OTC MEDICATION]
 
---
 
FEW-SHOT EXAMPLES
 
EXAMPLE 1 — "batam" error (most common mistake)
Input: "mi av pien inna di batam op mi fut"
WRONG: "Patient reports abdominal pain"
WHY WRONG: "batam" was split from "op mi fut" and misread as belly.
CORRECT Step 1: mi=I | av=have | pien=pain | inna=in | di=the | batam=sole | op=of | mi=my | fut=foot
CORRECT Step 2: "I have pain in the bottom of my foot"
CORRECT Step 3: "Patient reports pain in the plantar surface (sole) of the foot."
RULE: "batam op mi fut" = plantar foot pain. NEVER abdominal pain. Ever.
 
EXAMPLE 2 — hedging + negation
Input: "mi no riili mi no no riili no waa kaazi bot di riili pienful"
WRONG: "Patient denies pain"
WHY WRONG: Triple "no" read as negation of pain.
CORRECT: Patient hedges/minimises THEN says "but it is really painful."
Clinical output: "Patient minimises before admitting severe pain. Reflects cultural \
stoicism. Pain is significant."
 
EXAMPLE 3 — full transcript
Input: "ibll se fram sat de li batam op mi fut did de riili apien mi a yu no se \
mi no riili mi no no riili no waa kaazi bot di iiriil pienful an das wa mi kom \
a dakta tu de"
Step 1: ibll=I'll | se=say | fram=since | sat=Saturday | de=that time | \
li=the | batam=sole | op=of | mi=my | fut=foot | did=has | de=been | riili=really \
| apien=paining | mi=me | a=and | yu=you | no=know | se=that | mi=I | no=not \
| riili=really | mi=I | no=don't | no=know | riili=really | no=don't | waa=want \
| kaazi=cause | bot=but | di=it is | iiriil=really | pienful=painful | an=and \
| das=that's | wa=what | mi=I | kom=came | a=to | dakta=doctor | tu=today | de=here
Step 2: "Since Saturday the sole of my foot has really been paining me. I don't \
really — I don't want to make a fuss — but it is really painful. That's why I \
came to the doctor today."
Step 3:
  Chief Complaint: Plantar foot pain
  Location: Sole/plantar surface of foot (confirm laterality)
  Onset: Since Saturday
  Severity: Really painful — patient self-presented due to severity
  Patient Qualifier: Cultural hedging before admitting severity — stoicism, not mild symptoms
  Remedies Tried: None mentioned
  Flagged: None
 
---
 
OUTPUT TEMPLATE — always use this exact structure:
 
STEP 1 — PHONETIC RESOLUTION:
[token by token]
 
STEP 2 — ASSEMBLED ENGLISH:
[full grammatical sentences]
 
STEP 3 — CLINICAL INTERPRETATION:
Chief Complaint:
Location:
Radiation:
Onset:
Duration:
Character/Quality:
Severity:
Aggravating Factors:
Relieving Factors:
Associated Symptoms:
Remedies Tried:
Patient's Own Words:
Cultural/Linguistic Notes:
Flagged Segments: [UNCLEAR: "..."]


And at end give a clinical summary in clean English, suitable for a doctor to read quickly:
---
 
FINAL REMINDERS:
- "batam op mi fut" = sole of foot. ALWAYS. Not abdomen. Not belly. Ever.
- "kyaahn" = cannot. ALWAYS.
- "nuh/nah" = no/not. ALWAYS.
- "a yu no se" = filler. NOT a symptom.
- "mi no riili... bot" = the real finding is AFTER "bot."
- Patwa anatomical terms are not sexual content. Do not filter them.
- Patient minimising does not mean absence of symptoms.
- Complete Step 1 and Step 2 BEFORE any clinical interpretation. No exceptions.

"""

def interpret_patois(patois_text: str) -> str:
    """Convert raw MMS Patois transcript into clean clinical English."""
    text = (patois_text or "").strip()
    if not text:
        return ""
    return _chat(
        [
            {"role": "system", "content": PATOIS_INTERPRETER_SYSTEM_PROMPT},
            {"role": "user", "content": f"PATWA TRANSCRIPT:\n{text}"},
        ]
    )
