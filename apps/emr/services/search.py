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
    return patient.medications.filter(status="active").order_by("drug_name_generic")


def active_problem_list_for_patient(patient):
    return patient.diagnoses.filter(status__in=["active", "chronic"]).order_by("diagnosis_rank", "-created_at")
