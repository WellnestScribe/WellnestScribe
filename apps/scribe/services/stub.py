"""Deterministic stub used when AI credentials are missing or SCRIBE_USE_REAL_AI=False.

Lets the UI/flow be tested end-to-end offline. Never ship to production.
"""

from __future__ import annotations

import textwrap

from .soap_generator import GeneratedNote


DISCLAIMER = "AI-generated draft — review and edit required before clinical use."


def _wrap(text: str) -> str:
    return textwrap.fill(text.strip(), width=84)


def fake_transcribe(file_path: str) -> str:
    return (
        "Patient is a 58 year old female presenting for hypertension follow up. "
        "Reports taking amlodipine 5 milligrams once daily as prescribed. "
        "Says her pressure was high last week. Denies chest pain or shortness of "
        "breath. On exam, blood pressure is 138 over 86, heart rate 72, "
        "respirations 16. Plan: increase amlodipine to 10 milligrams once daily, "
        "recheck blood pressure in two weeks, continue low salt diet."
    )


def fake_generate_note(
    transcript: str,
    *,
    note_format: str = "soap",
    specialty: str = "general",
    length_mode: str = "normal",
    custom_instructions: str = "",
) -> GeneratedNote:
    if note_format == "narrative":
        narrative = _wrap(
            "Patient seen today for routine hypertension follow-up. Reports good "
            "compliance with amlodipine 5mg once daily. No chest pain, no shortness "
            "of breath. BP measured at 138/86 with HR 72. Hypertension noted to be "
            "suboptimally controlled. Amlodipine increased to 10mg OD; BP recheck "
            "scheduled in two weeks; advised continued low-salt diet."
        )
        return GeneratedNote(
            note_format="narrative",
            full_note=f"{narrative}\n\n{DISCLAIMER}",
            narrative=narrative,
        )

    if note_format == "chart":
        chart = (
            "Reason for visit: Routine HTN follow-up.\n"
            "Subjective: Reports compliance with amlodipine 5mg OD. No CP, no SOB.\n"
            "Objective: BP 138/86, HR 72, RR 16.\n"
            "Assessment: HTN — suboptimally controlled.\n"
            "Plan: Increase amlodipine to 10mg OD. Recheck BP in 2 weeks. Continue low-salt diet.\n"
            "Follow-up: 2 weeks."
        )
        return GeneratedNote(
            note_format="chart",
            full_note=f"{chart}\n\n{DISCLAIMER}",
        )

    s = (
        "S:\n"
        "CC: Routine hypertension follow-up.\n"
        "HPI: 58 y/o female. Reports taking amlodipine 5mg OD as prescribed. "
        "Notes home BP was elevated last week. Denies CP, SOB, headache.\n"
        "Current Medications: Amlodipine 5mg PO OD.\n"
        "Allergies: NKA."
    )
    o = "O:\nVitals: BP 138/86 | HR 72 | RR 16."
    a = "A:\n1. Hypertension (uncontrolled) — target BP not achieved on current regimen."
    p = (
        "P:\n"
        "1. Hypertension\n"
        "   - Medications: Amlodipine 10mg PO OD x 30 days\n"
        "   - Follow-up: BP recheck in 2 weeks\n"
        "   - Lifestyle: Continue low-salt diet."
    )
    full = f"{s}\n\n{o}\n\n{a}\n\n{p}\n\n{DISCLAIMER}"
    return GeneratedNote(
        note_format="soap",
        full_note=full,
        subjective=s.split("S:\n", 1)[-1],
        objective=o.split("O:\n", 1)[-1],
        assessment=a.split("A:\n", 1)[-1],
        plan=p.split("P:\n", 1)[-1],
    )
