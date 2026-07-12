"""Per-call GPT usage capture for real cost measurement (task T5).

Every GPT call funnels through soap_generator._chat (and the streaming path),
which calls record_call() here with the API response's `usage`. A thread-local
context lets the view tag each call with its session / doctor / call type without
threading params through the whole pipeline. Best-effort — never raises into a
request. omniASR (audio) cost is derived separately from session duration; this
module only measures the GPT side, which is the dominant, previously-estimated cost.
"""
from __future__ import annotations

import contextlib
import logging
import threading

logger = logging.getLogger(__name__)

# Azure GPT-5.4 list price (USD per token). Recorded onto each row so a logged
# cost stays fixed even if list prices change later. Reasoning tokens are part
# of completion_tokens and bill at the output rate.
INPUT_USD_PER_TOKEN = 2.50 / 1_000_000
OUTPUT_USD_PER_TOKEN = 15.00 / 1_000_000

_ctx = threading.local()


def set_context(*, session_id=None, doctor_id=None, call_type=""):
    _ctx.session_id = session_id
    _ctx.doctor_id = doctor_id
    _ctx.call_type = call_type or ""


def clear_context():
    for attr in ("session_id", "doctor_id", "call_type"):
        if hasattr(_ctx, attr):
            delattr(_ctx, attr)


@contextlib.contextmanager
def usage_context(*, session_id=None, doctor_id=None, call_type=""):
    """Tag every GPT call made inside the block. Always clears on exit so a
    reused (gthread) worker thread can't leak a stale session tag."""
    set_context(session_id=session_id, doctor_id=doctor_id, call_type=call_type)
    try:
        yield
    finally:
        clear_context()


def record_call(model, usage_obj):
    """Persist one ModelUsageLog row from an API response's usage. Never raises."""
    try:
        if usage_obj is None:
            return
        prompt = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        details = getattr(usage_obj, "completion_tokens_details", None)
        reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)
        total = int(getattr(usage_obj, "total_tokens", 0) or (prompt + completion))
        input_cost = prompt * INPUT_USD_PER_TOKEN
        output_cost = completion * OUTPUT_USD_PER_TOKEN

        from scribe.models import ModelUsageLog
        ModelUsageLog.objects.create(
            session_id=getattr(_ctx, "session_id", None),
            doctor_id=getattr(_ctx, "doctor_id", None),
            call_type=getattr(_ctx, "call_type", "") or "",
            model=str(model or "")[:100],
            prompt_tokens=prompt,
            completion_tokens=completion,
            reasoning_tokens=reasoning,
            total_tokens=total,
            input_cost=round(input_cost, 6),
            output_cost=round(output_cost, 6),
            total_cost=round(input_cost + output_cost, 6),
        )
    except Exception:  # noqa: BLE001 — measurement must never break a note
        logger.debug("usage.record_call failed", exc_info=True)
