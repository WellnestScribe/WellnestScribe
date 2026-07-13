"""Patient search tuned for a small-to-medium clinic deployment.

We stay database-agnostic here so SQLite dev, MySQL prod, and future PostgreSQL
all behave acceptably. The sequence is:
1. Exact identifier match.
2. Case-insensitive prefix/contains search.
3. Lightweight fuzzy fallback over a bounded candidate set.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from django.db.models import Q

from emr.models import Patient


def search_patients(organisation, term: str, limit: int = 25):
    term = (term or "").strip()
    qs = Patient.objects.filter(organisation=organisation)
    if not term:
        return qs.order_by("-updated_at")[:limit]

    exact_qs = qs.filter(
        Q(nhf_card_number__iexact=term)
        | Q(trn__iexact=term)
        | Q(phone_primary__iexact=term)
        | Q(phone_secondary__iexact=term)
    )
    exact_results = list(exact_qs[:limit])
    if exact_results:
        return exact_results

    contains_qs = qs.filter(
        Q(legal_first_name__icontains=term)
        | Q(legal_last_name__icontains=term)
        | Q(preferred_name__icontains=term)
        | Q(community__icontains=term)
        | Q(district__icontains=term)
        | Q(parish__icontains=term)
    ).order_by("legal_last_name", "legal_first_name")[:limit]
    contains_results = list(contains_qs)
    if contains_results:
        return contains_results

    candidates = list(qs.order_by("-updated_at")[:200])
    scored = []
    lowered_term = term.lower()
    for patient in candidates:
        haystacks = [
            patient.full_name.lower(),
            patient.display_name.lower(),
            (patient.nhf_card_number or "").lower(),
            (patient.phone_primary or "").lower(),
        ]
        score = max(SequenceMatcher(None, lowered_term, hay).ratio() for hay in haystacks if hay)
        if score >= 0.55:
            scored.append((score, patient))

    scored.sort(key=lambda item: (-item[0], item[1].legal_last_name, item[1].legal_first_name))
    return [patient for _, patient in scored[:limit]]


def active_medications_for_patient(patient):
    """Active medications, most-recent visit first, deduped by drug so the same
    medicine prescribed across several visits shows once (the latest)."""
    qs = (
        patient.medications.filter(status="active")
        .select_related("encounter")
        .order_by("-encounter__encounter_date", "-created_at")
    )
    seen: set[str] = set()
    out = []
    for med in qs:
        key = (med.drug_name_generic or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(med)
    return out


def active_problem_list_for_patient(patient):
    """Longitudinal problem list: confirmed active/chronic diagnoses across the
    patient's history (a chronic problem persists across visits by design).
    Resolved and 'suspected' diagnoses are excluded; entries are deduped by ICD
    code and ordered most-recent visit first, each tagged with its source visit."""
    qs = (
        patient.diagnoses.filter(status__in=["active", "chronic"])
        .select_related("encounter")
        .order_by("-encounter__encounter_date", "diagnosis_rank", "-created_at")
    )
    seen: set[str] = set()
    out = []
    for dx in qs:
        key = (dx.icd10_code or dx.icd10_description or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dx)
    return out
