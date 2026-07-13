# WellNest — Prompt Caching (measurement) + the note-generation slowdown

> What was changed, why, and how to verify. **No prompts were changed** — this is
> Phase 1 (measurement) only. Last updated 2026-07-12.

---

## What prompt caching is (and how it saves money)

Every note sends the model a large **static instruction block** (`MASTER_SYSTEM_PROMPT` +
language context + specialty + the doctor's terms) — ~8,000 tokens — followed by the small
**variable** part (this patient's transcript, ~1,000 tokens). That static block is ~90% of the
input and is (nearly) identical every time.

**Azure caches a repeated ≥1024-token prefix and bills it ~50% cheaper.** So instead of paying
full price to "re-read" the 8,000-token instruction sheet every note, you pay full price only for
the ~1,000-token transcript and half price for the cached instructions.

```
No cache : 9,000 tok x $2.50/1M                                = $0.0225 input
Cached   : 1,000 x $2.50/1M  +  8,000 x $1.25/1M (50% off)     = $0.0125 input   (~44% less input)
```

Caveats: the cache stays warm ~5–10 min, so the benefit is biggest with **back-to-back** notes
(a busy clinic), and it only helps if the leading prompt is **byte-identical** between calls.

---

## Phase 1 — what changed (measurement only, zero prompt changes)

| File | Change |
|---|---|
| `apps/scribe/models.py` | `ModelUsageLog` gains a `cached_tokens` field |
| `apps/scribe/services/usage.py` | `record_call()` reads `usage.prompt_tokens_details.cached_tokens` |
| `apps/scribe/migrations/0027_modelusagelog_cached_tokens.py` | the field migration |
| `apps/scribe/management/commands/ai_cost_report.py` | prints a **cache-hit %** + estimated saving |

`total_cost` stays at **list price** (an upper bound) so the ledger is consistent; the saving is
shown separately from `cached_tokens`. **No file under `services/prompts.py` or the prompt
assembly was touched** — note output is byte-for-byte unchanged.

### How to measure it
1. On the deployed app, generate **two notes back-to-back** (within a few minutes).
2. Run: `python manage.py ai_cost_report --hours 1`
3. Read the new line: `Prompt cache: X / Y prompt tokens cached (Z% hit) -> est. saving ~$…`

- **High hit (e.g. 50–90%)** → Azure is already caching; we're done, no prompt changes needed.
- **~0% hit on fresh, back-to-back notes** → the prefix isn't repeating; then **Phase 2** (below).

> First reading after this change showed 0% — but those rows **predate the field** (default 0), so
> it isn't real data yet. Re-measure with fresh notes.

---

## Phase 2 — reorder prompts (ONLY if fresh measurement shows ~0%) — NOT DONE

Would touch, carefully and with a before/after note diff to prove output is identical:
- `apps/scribe/services/soap_generator.py` — `_system_prompt()`: make the universal static block a
  strict, byte-identical leading prefix; per-doctor bits trail it; confirm
  `interpret_and_generate_soap()` uses the same stable prefix.
- `apps/scribe/services/prompts.py` — ensure `{transcript}` is the final token of the user prompt.

Not started — pending measured justification + go-ahead.

---

## The note-generation slowdown (investigated 2026-07-12)

Measured from `ScribeSession.timings`:

| Date | Pipeline | generation_ms | interpret_ms | Total |
|---|---|---|---|---|
| 07-11 | combined (1 call) | ~11,000–13,000 | – | ~12 s |
| 07-12 | combined (1 call) | **~21,500** | – | ~21 s |
| 07-12 | **two-call fallback** | ~10,500 | **~24,400** | **~35 s** |

**Root cause is mostly Azure-side:** the `gpt-5-chat` deployment roughly **doubled in latency**
(combined generation ~12 s → ~21 s), plus occasional **fallback to the slower two-call pipeline**
(interpret **~24 s** + generate ~10 s ≈ 35 s), which fires when the single combined call errors.

**What we can do:**
- **Azure (biggest lever):** check the deployment's rate-limit / quota (throttling shows as slow
  responses); consider a less-loaded region or a provisioned-throughput deployment.
- **Reduce the two-call fallbacks:** check `logs/` for why the combined call errored on 07-12; the
  combined path is ~2–3× faster, so keeping it on the fast path matters.
- **Prompt caching** trims prompt-processing time a little (faster once the prefix is cached).

Not a code regression on our side — the combined pipeline is still the default; it fell back
intermittently and Azure itself was slower.
