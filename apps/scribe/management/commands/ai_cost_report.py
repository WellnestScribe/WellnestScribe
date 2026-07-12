"""Real per-note AI cost report from measured token usage (task T5).

Run after a control test to turn the estimated cost numbers in
docs/July_2026_Financials_Estimate.md into measured facts.

    python manage.py ai_cost_report --hours 6
    python manage.py ai_cost_report --session 123
    python manage.py ai_cost_report --hours 24 --json

Reads ModelUsageLog (GPT tokens + cost, recorded by services.usage) and folds in
omniASR/audio cost derived from each session's recorded duration.
"""
from __future__ import annotations

import json as _json
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

# omniASR measured rate (see financials doc §1.1): $0.0325 / audio-hour on T4.
OMNIASR_USD_PER_AUDIO_SEC = 0.0325 / 3600
OMNIASR_BUFFERED_PER_AUDIO_SEC = 0.05 / 3600  # includes cold-start / whole-request buffer


class Command(BaseCommand):
    help = "Report measured per-note AI cost from logged token usage."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Look back this many hours.")
        parser.add_argument("--session", type=int, default=None, help="Restrict to one session pk.")
        parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")

    def handle(self, *args, **opts):
        from scribe.models import ModelUsageLog, ScribeSession

        cutoff = timezone.now() - timedelta(hours=opts["hours"])
        qs = ModelUsageLog.objects.filter(created_at__gte=cutoff)
        if opts["session"]:
            qs = qs.filter(session_id=opts["session"])
        rows = list(qs.order_by("created_at"))

        if not rows:
            self.stdout.write(self.style.WARNING(
                "No ModelUsageLog rows in the window. Run a note generation first "
                "(and confirm SCRIBE_USE_REAL_AI=True)."
            ))
            return

        # Group by session (None = untagged calls, e.g. demographics).
        by_session: dict = defaultdict(list)
        for r in rows:
            by_session[r.session_id].append(r)

        # audio durations for the sessions we saw. duration_seconds is often 0 for
        # uploaded files; the true measured length lives in timings.audio_seconds.
        sess_ids = [s for s in by_session if s]
        durations = {}
        for s in ScribeSession.objects.filter(pk__in=sess_ids).only("pk", "duration_seconds", "timings"):
            durations[s.pk] = s.duration_seconds or (s.timings or {}).get("audio_seconds") or 0

        notes = []
        for sid, logs in by_session.items():
            prompt = sum(l.prompt_tokens for l in logs)
            completion = sum(l.completion_tokens for l in logs)
            reasoning = sum(l.reasoning_tokens for l in logs)
            gpt_cost = float(sum(l.total_cost for l in logs))
            audio_s = (durations.get(sid) or 0) if sid else 0
            omni_cost = audio_s * OMNIASR_USD_PER_AUDIO_SEC
            omni_cost_buf = audio_s * OMNIASR_BUFFERED_PER_AUDIO_SEC
            call_types = ",".join(sorted({l.call_type or "?" for l in logs}))
            notes.append({
                "session": sid,
                "calls": len(logs),
                "call_types": call_types,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "reasoning_tokens": reasoning,
                "gpt_cost": round(gpt_cost, 5),
                "audio_seconds": round(audio_s, 1),
                "omniasr_cost": round(omni_cost, 5),
                "total_cost": round(gpt_cost + omni_cost, 5),
                "total_cost_buffered": round(gpt_cost + omni_cost_buf, 5),
            })

        note_notes = [n for n in notes if n["session"]]  # real per-note rows
        total_gpt = sum(n["gpt_cost"] for n in notes)
        total_omni = sum(n["omniasr_cost"] for n in notes)
        total = total_gpt + total_omni
        n_notes = len(note_notes) or 1
        avg_note = sum(n["total_cost"] for n in note_notes) / n_notes if note_notes else 0
        avg_note_buf = sum(n["total_cost_buffered"] for n in note_notes) / n_notes if note_notes else 0
        gpt_share = (total_gpt / total * 100) if total else 0

        if opts["json"]:
            self.stdout.write(_json.dumps({
                "window_hours": opts["hours"],
                "notes": notes,
                "totals": {
                    "gpt_cost": round(total_gpt, 5),
                    "omniasr_cost": round(total_omni, 5),
                    "total_cost": round(total, 5),
                    "gpt_share_pct": round(gpt_share, 1),
                    "avg_cost_per_note": round(avg_note, 5),
                    "avg_cost_per_note_buffered": round(avg_note_buf, 5),
                    "notes_counted": len(note_notes),
                },
            }, indent=2))
            return

        w = self.stdout.write
        w("")
        w(self.style.MIGRATE_HEADING(f"AI cost — measured (last {opts['hours']}h)"))
        w("-" * 96)
        w(f"{'sess':>5} {'calls':>5} {'p_tok':>7} {'c_tok':>7} {'reason':>7} "
          f"{'GPT$':>9} {'audio_s':>8} {'omni$':>8} {'note$':>8}  types")
        for n in notes:
            w(f"{str(n['session'] or '—'):>5} {n['calls']:>5} {n['prompt_tokens']:>7} "
              f"{n['completion_tokens']:>7} {n['reasoning_tokens']:>7} "
              f"{n['gpt_cost']:>9.5f} {n['audio_seconds']:>8.1f} {n['omniasr_cost']:>8.5f} "
              f"{n['total_cost']:>8.5f}  {n['call_types']}")
        w("-" * 96)
        w(f"Notes counted: {len(note_notes)}   GPT is {gpt_share:.1f}% of measured cost")
        w(f"Total GPT ${total_gpt:.5f} + omniASR ${total_omni:.5f} = ${total:.5f}")
        w(self.style.SUCCESS(
            f"AVG COST / NOTE = ${avg_note:.4f}  (buffered omniASR: ${avg_note_buf:.4f})"))
        w("")
        # Margin implications at the cap volumes from the financials doc.
        for price, notes_cap, plan in ((94, 500, "Standard"), (190, 1100, "Professional")):
            if avg_note_buf > 0:
                cost = avg_note_buf * notes_cap + 15  # +$15 infra
                margin = (price - cost) / price * 100
                w(f"  {plan} @ ${price}, {notes_cap} notes: cost ${cost:.2f} -> margin {margin:.0f}%")
        w("")
        w("Compare against docs/July_2026_Financials_Estimate.md §3 (est. ~$0.045/note).")
