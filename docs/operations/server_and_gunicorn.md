# WellNest — Server & Gunicorn Configuration (the worker fix)

> Why the site froze for everyone, and the one server-config change that fixed it.
> Operational / core-systems reference. Full scale path in `../roadmap/scaling_architecture.md`.
> Last updated 2026-07-12.

---

## The symptom

When any **one** user opened the **Worklist & queue** page, the whole site went slow or **froze
for everyone** — **504 Gateway Timeouts** on Azure — and even signing in was slow with a single user.

## Root cause — the original Startup Command

The Azure App Service Startup Command was effectively:

```
python manage.py migrate && python manage.py collectstatic && gunicorn wellnest.wsgi --bind=0.0.0.0 --timeout 600
```

`gunicorn wellnest.wsgi` with **no worker flags** falls back to gunicorn's **defaults**:

- **1 worker, `sync` class, 1 thread** → the entire site serves **exactly one request at a time**.
- `--timeout 600` → a single stuck request can hold that one slot for **10 minutes** before it's killed.

Add the old always-on SSE (held a worker ~180 s per user) plus continuous worklist polling, and
**2–3 online users were enough to occupy the only slot → site-wide freeze / 504.**

## The fix — gthread with more workers + threads

Set **Azure → Configuration → General settings → Startup Command** to:

```
gunicorn wellnest.wsgi:application --worker-class gthread --workers 1 --threads 8 --timeout 300 --graceful-timeout 30 --max-requests 1200 --max-requests-jitter 150 --worker-tmp-dir /dev/shm --bind=0.0.0.0:8000
```

| Flag | Before | After | Why |
|---|---|---|---|
| worker-class | `sync` | **`gthread`** | threads overlap DB waits |
| workers × threads | 1 × 1 = **1** | **1 × 8 = 8** | concurrent requests |
| timeout | 600 | 300 | a hung thread recycles sooner, and now only ties up 1 of 8 lanes instead of the whole site |
| max-requests | — | 1200 (+jitter) | recycle the worker to cap memory creep |

> **⚠️ Keep it to ONE worker on B1 — use threads, not workers, for concurrency.** The
> ambient-transcription job registry is an **in-memory dict** (`apps/scribe/services/triage_jobs.py`).
> The upload submits the job to one process and the browser then **polls** for the result; with
> **multiple workers** the poll can land on a different process that doesn't have the job →
> **`HTTP 404 {"ok": false, "error": "Not found."}`** and the upload never transcribes. A single
> worker with 8 threads shares one memory space, so submit and poll always agree — and on a 1-vCPU
> B1 extra worker *processes* add no CPU anyway. Going multi-worker / multi-instance later requires
> a **DB- or Redis-backed job store** first (see `../roadmap/scaling_architecture.md`, Layer 2).

**Also set:** `DEBUG=False`, and **Always On = On** (stops idle spin-down → no cold-start on the
first request after a quiet period). **Move `migrate` + `collectstatic` OUT** of the Startup
Command (run them at build/deploy, not on every boot — that made cold starts 30–60 s).

## Why gthread, not just more sync workers

The app is **I/O-bound** — most of a request is spent **waiting** on the remote Aiven DB
(~125 ms/query). A `sync` worker sits idle-but-busy during that wait; `gthread` lets its other
threads use the wait time. So **2 workers × 4 threads ≈ 8 concurrent requests** on a 1-vCPU B1,
where 2 sync workers would only give 2.

## Capacity

| Config | Concurrent requests | ~Active users on B1 |
|---|---|---|
| 1 sync worker (old) | 1 | ~1–3 (froze) |
| **gthread 2 × 4 (current)** | ~8 | **~30–60** |
| gthread 3 × 4 (if RAM allows) | ~12 | more |

Beyond that: **co-locate the DB in the app's Azure region** (biggest single win — kills the
~125 ms/query cross-region latency), then move to a multi-core SKU and **scale out** (N instances,
autoscale on CPU). Full plan: `../roadmap/scaling_architecture.md`.

## Verify it's actually running

- **Server Monitor page** — `/scribe/ops/server/` (admin) shows the **live gunicorn worker count**, CPU %, memory %, and a DB round-trip ping.
- **SSH** into the App Service → `ps aux | grep gunicorn` → expect **1 master + N workers**.
- **Azure Log stream** → the gunicorn boot line should show `--worker-class gthread` and `workers: N`.

If the worker count is **1**, the Procfile/Startup Command isn't in effect — a custom command in
the portal overrides the repo `Procfile`. Clear it or paste the command above.

## Related app-side changes (so polling doesn't refill the lanes)

The worker fix gives concurrency; these keep each request cheap so it stays that way:

- The QR-handoff **SSE is scoped to `/scribe/` only** (was opening on every page, holding a worker per user).
- Worklist/queue **short-poll lean fragments**, self-throttling (backoff) with a signature-diff so the DOM only swaps on real change; pauses when the tab is hidden.
- `SESSION_SAVE_EVERY_REQUEST=False`; `PlatformControl` cached 30 s; the worklist `Max(...)` annotation removed; the vitals **N+1 batched** into one query.

*Repo: `Procfile` (release + web command), `wellnest/settings.py` (session/DB), `wellnest/middleware.py`.*
