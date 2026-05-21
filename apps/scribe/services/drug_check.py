"""Drug interaction checker — Jamaican context.

Pipeline:
  1. Caller passes raw drug names (whatever the doctor typed).
  2. We resolve each through the DrugAlias table → (generic, drug_class).
     - Brand match wins, then generic-name match (so "Diclofenac" works too).
  3. Anything we can't resolve gets tagged UNRECOGNIZED — the AI is told to
     not guess about these. Better to ask the doctor than invent.
  4. The resolved payload (canonical generics + classes + context) is sent
     to the chat model with DRUG_INTERACTION_PROMPT.
  5. We parse the JSON response, defend against markdown fences and partial
     output, and return a normalized dict.

Why no per-pair cache (yet):
  Interactions are N-way contextual (age, conditions, allergies, doses).
  A cached (drug_a, drug_b) lookup would miss those modifiers and risk
  serving stale advice. We log every check to DrugInteractionCheck for
  later analysis — cache later if and only if traffic shape justifies it.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from django.conf import settings

from .clients import AIConfigError
from .prompts import DRUG_INTERACTION_PROMPT
from .soap_generator import _chat


logger = logging.getLogger(__name__)


EMPTY_RESULT: dict[str, Any] = {
    "summary": "",
    "overall_severity": "none",
    "findings": [],
    "unrecognized": [],
    "disclaimer": (
        "AI advisory only — not a substitute for clinical judgment. "
        "Always cross-check with a current drug reference."
    ),
}


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def resolve_drug(name: str) -> dict:
    """Resolve a single drug input to (canonical generic, class) via DrugAlias.

    Lookup order:
      1. Exact brand match (case-insensitive)
      2. Exact generic match (case-insensitive)
      3. Substring brand match (so "Voltarol SR 75" still finds Voltarol)
      4. Unresolved — flag for the AI.
    """
    from ..models import DrugAlias  # local to avoid circular import at app load

    raw = _normalise(name)
    if not raw:
        return {"input": name, "resolved": False, "generic": "", "drug_class": "", "via": "empty"}

    qs = DrugAlias.objects.all()
    by_brand = qs.filter(brand_name__iexact=raw).first()
    if by_brand:
        return {
            "input": name, "resolved": True,
            "generic": by_brand.generic_name,
            "drug_class": by_brand.drug_class,
            "via": "brand_exact",
        }
    by_generic = qs.filter(generic_name__iexact=raw).first()
    if by_generic:
        return {
            "input": name, "resolved": True,
            "generic": by_generic.generic_name,
            "drug_class": by_generic.drug_class,
            "via": "generic_exact",
        }
    # Substring on brand (only for inputs >= 4 chars to avoid silly matches)
    if len(raw) >= 4:
        partial = qs.filter(brand_name__icontains=raw).first()
        if partial:
            return {
                "input": name, "resolved": True,
                "generic": partial.generic_name,
                "drug_class": partial.drug_class,
                "via": "brand_partial",
            }
    return {"input": name, "resolved": False, "generic": "", "drug_class": "", "via": "unresolved"}


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def _parse_ai_json(raw: str) -> dict:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def _normalize_result(parsed: dict) -> dict:
    out = copy.deepcopy(EMPTY_RESULT)
    if not isinstance(parsed, dict):
        return out
    out["summary"] = str(parsed.get("summary") or "")
    sev = (parsed.get("overall_severity") or "none").strip().lower()
    if sev not in ("critical", "major", "moderate", "minor", "none"):
        sev = "none"
    out["overall_severity"] = sev
    findings = parsed.get("findings")
    if isinstance(findings, list):
        out["findings"] = [_clean_finding(f) for f in findings if isinstance(f, dict)]
    unrec = parsed.get("unrecognized")
    if isinstance(unrec, list):
        out["unrecognized"] = [
            {
                "input": str(u.get("input") or ""),
                "reason": str(u.get("reason") or ""),
                "ask_doctor": str(u.get("ask_doctor") or ""),
            }
            for u in unrec if isinstance(u, dict)
        ]
    if parsed.get("disclaimer"):
        out["disclaimer"] = str(parsed["disclaimer"])
    return out


def _clean_finding(f: dict) -> dict:
    sev = (f.get("severity") or "minor").strip().lower()
    if sev not in ("critical", "major", "moderate", "minor"):
        sev = "minor"
    conf = (f.get("confidence") or "medium").strip().lower()
    if conf not in ("high", "medium", "low"):
        conf = "medium"
    return {
        "type": str(f.get("type") or "interaction"),
        "severity": sev,
        "confidence": conf,
        "involves": [str(x) for x in (f.get("involves") or []) if str(x).strip()],
        "mechanism": str(f.get("mechanism") or ""),
        "clinical_effect": str(f.get("clinical_effect") or ""),
        "recommendation": str(f.get("recommendation") or ""),
        "alternatives": [str(x) for x in (f.get("alternatives") or []) if str(x).strip()],
        "evidence_strength": str(f.get("evidence_strength") or ""),
    }


def check_interactions(
    *,
    current_meds: list[str],
    proposed_med: str,
    herbs: list[str] | None = None,
    patient_context: dict | None = None,
) -> dict:
    """Run an interaction check. Returns the normalized result dict.

    Stub mode returns a deterministic empty result so the UI keeps working
    without AI keys.
    """
    herbs = herbs or []
    patient_context = patient_context or {}

    resolved_current = [resolve_drug(m) for m in current_meds if _normalise(m)]
    resolved_proposed = resolve_drug(proposed_med)
    resolved_herbs = [{"input": _normalise(h), "resolved": False, "kind": "herb"} for h in herbs if _normalise(h)]

    if not getattr(settings, "SCRIBE_USE_REAL_AI", False):
        out = copy.deepcopy(EMPTY_RESULT)
        out["summary"] = "Stub mode — no AI configured. Set SCRIBE_USE_REAL_AI=True."
        out["unrecognized"] = [
            {"input": d["input"], "reason": "stub", "ask_doctor": ""}
            for d in resolved_current + [resolved_proposed] + resolved_herbs
            if not d.get("resolved")
        ]
        return out

    payload = {
        "current_medications": resolved_current,
        "proposed_medication": resolved_proposed,
        "herbal_remedies": resolved_herbs,
        "patient_context": {
            "age": patient_context.get("age", ""),
            "sex": patient_context.get("sex", ""),
            "conditions": patient_context.get("conditions") or [],
            "allergies": patient_context.get("allergies") or [],
        },
    }
    user_msg = DRUG_INTERACTION_PROMPT.format(payload=json.dumps(payload, indent=2))
    try:
        raw = _chat(
            [
                {"role": "system", "content": "You are a strict JSON-only clinical pharmacology assistant."},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=2400,
        )
    except AIConfigError as exc:
        logger.warning("Drug check AI unavailable: %s", exc)
        out = copy.deepcopy(EMPTY_RESULT)
        out["summary"] = f"AI not available: {exc}"
        return out
    except Exception as exc:  # noqa: BLE001
        # OpenAI/Azure can throw RateLimitError, APIError, etc. Surface as a
        # structured result so the UI shows a friendly message instead of a
        # 500. Also include the unresolved-drug list so the doctor can still
        # see which inputs the alias table didn't recognize.
        logger.exception("Drug check AI call failed")
        out = copy.deepcopy(EMPTY_RESULT)
        msg = str(exc).strip() or exc.__class__.__name__
        # OpenAI errors often carry "Error code: NNN" — pull the code for clarity.
        if "Error code: 429" in msg or "rate" in msg.lower():
            out["summary"] = "AI provider rate-limited or temporarily unavailable. Try again in a moment."
        elif "Error code: 5" in msg:
            out["summary"] = "AI provider had a backend error. Try again shortly."
        else:
            out["summary"] = f"AI call failed: {msg[:200]}"
        out["unrecognized"] = [
            {"input": d["input"], "reason": "Not in alias table; AI was not reachable to verify.", "ask_doctor": ""}
            for d in resolved_current + [resolved_proposed] + resolved_herbs
            if not d.get("resolved")
        ]
        return out

    parsed = _parse_ai_json(raw)
    return _normalize_result(parsed)
