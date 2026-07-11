# WellNest — Sustainable Scaling Architecture (hundreds → thousands of users)

> Target: hundreds to thousands of doctors/nurses online at once, most of them
> **staring at the real-time worklist**, with no slowdown for anyone. This is the
> definitive plan. Ordered by leverage.

## The one rule that governs everything
**A server request-slot (worker/thread) may be held only for the milliseconds it takes
to answer a request — never per-user, never per-page.** The instant anything holds a slot
for seconds/minutes per user, max users = number of slots. Everything below enforces this.

---

## Layer 0 — the bug that was breaking it (FIXED in code)
- The QR-handoff **SSE (`EventSource`) opened on every page** and the server held it for 180s
  **per user**. With `gunicorn --workers 2`, two online users = both slots held = whole site
  frozen. → **Scoped the SSE to `/scribe/` pages only** (where the handoff happens). The worklist
  and appointments now hold **zero** connections.
- The worklist ran a `Max(encounters__encounter_date)` annotation (JOIN over all encounters +
  GROUP BY + filesort) → removed; now a bounded `order_by(-updated_at)` query.
These two fixes take a single B1 from "freezes at ~2 users" to "fine for a small clinic," but
**do not** get you to thousands. For that, the layers below.

---

## Layer 1 — real-time worklist without per-user cost (the core design)
Thousands of people watching the same per-clinic queue is a **fan-out** problem.

### DECISION: short polling with a lean endpoint (NO Redis for now)
Redis (Azure Cache) is expensive, so we're **not** adding it. Instead:
- The worklist **short-polls `/emr/api/queue/` every ~12 s** (already wired in `_waiting_queue.html`).
  Each poll is a stateless request that **releases the slot instantly** — no held connections.
- **The endpoint must be O(1) queries** so polling doesn't multiply DB load. ✅ Done: `waiting_queue_api`
  now fetches the whole queue's latest vitals in **one** query instead of one-per-patient (was an N+1).
  Each poll is ~2–3 fast indexed queries regardless of queue size.
- **This gets you to hundreds** without Redis: e.g. 300 users across 30 clinics polling every 12 s ≈
  25 req/s, each ~3 quick queries → an easy load for a right-sized instance + co-located DB.
- **If** DB load ever becomes the ceiling, the drop-in upgrade is a **short per-org cache**
  (`django.core.cache`, locmem or Redis) so many watchers of one clinic share one computed result.
  Deferred until measured — not needed now.

### Upgrade (later): Django Channels + Redis websockets (push)
- Websockets grouped **by org**; when the queue changes, broadcast to that org's group. Instant,
  zero polling. Needs ASGI (uvicorn/daphne) + Redis channel layer + async-safe consumers.
- More infra/complexity. Do this only when polling latency actually bothers users. Polling first.

**Either way:** no long-held connection per user. Polling = short requests; Channels = cheap async
idle sockets. The current always-on sync SSE is the one thing to never do.

---

## Layer 2 — make the app stateless (required to scale out)
You cannot run multiple instances until nothing lives in one process's memory.
- **In-memory state must move to Redis.** Today the QR scan uses an in-process dict
  (`_pending_scans`) — works on one instance only; move it to Redis (or drop it when the SSE
  becomes on-demand/Channels).
- **Sessions:** DB-backed (fine) or Redis.
- **Cache hot, repeated reads in Redis:** platform settings, org membership, the per-org queue —
  so a page render isn't 12 DB round-trips every time.
- Result: every instance is identical and disposable.

## Layer 3 — scale the compute horizontally (this is what gives you "thousands")
- **A B1 is 1 vCPU.** Python's GIL means one core ≈ one CPU task at a time. No code makes 1 core
  serve thousands. You must add cores/instances.
- **Azure App Service scale-out:** run **N identical instances** behind the built-in load balancer,
  **auto-scale on CPU** (e.g., 2 → 20 instances). This is the horsepower for hundreds/thousands.
- **SKU:** move off B1 to **P1v3/P2v3** (multi-core, more RAM) as the per-instance base, then scale
  out. B1 is a pilot box only.
- **Server command:** `gunicorn --worker-class gthread --workers <cores> --threads 4` (polling), or
  **uvicorn ASGI workers** if you adopt Channels websockets.

## Layer 4 — right-size the database (the shared bottleneck)
Every instance shares one DB, so it's the ceiling once the web tier scales.
- **Co-locate**: DB in the **same Azure region** as the app (cross-region ≈ 125 ms/query × 12 = 1.5 s/page).
- **Index** hot queries (queue by `org+date`, patient search) — mostly done.
- **Bound connections**: N instances × workers × threads can blow past MySQL's connection cap —
  use modest `CONN_MAX_AGE` + a pooler (e.g., ProxySQL) or a managed pool.
- **Read replica** for heavy read traffic (worklist/search) if one primary isn't enough.
- **Cache reads in Redis** (Layer 1/2) so most page loads never touch MySQL.

## Layer 5 — keep the heavy/slow work off the web tier (mostly already true)
- **AI is external and scales on its own:** omniASR on Modal (GPU autoscale), GPT-5.4 on Azure.
  The web app only orchestrates — good. Keep it that way.
- **Long tasks** (email/WhatsApp reminders, exports, any batch) → a **background worker/queue**
  (Azure queue + a worker dyno, or Celery+Redis), never inside a web request.
- **Static/media**: WhiteNoise now; move static + document images to **Azure Blob/CDN** to offload
  the app instances.

---

## Capacity, honestly
| Setup | Concurrent users before slowdown |
|---|---|
| Old (2 sync workers, always-on SSE) | ~2 (froze) |
| + SSE scoped + gthread 2×4 on B1 | dozens (light use) |
| + cached-queue polling + Redis + stateless | hundreds on a P-series instance |
| + horizontal auto-scale (N instances) + read replica | thousands |

## Do-this order
1. ✅ **Scope the SSE** to `/scribe/` + **fix the worklist query** (done, in code — needs deploy).
2. **Cached per-org queue + polling endpoint** (`django.core.cache`; works with locmem locally,
   Redis in prod). Biggest scale win after Layer 0.
3. **Provision Azure Cache for Redis**; point `CACHES` (+ move `_pending_scans`) to it; make the app stateless.
4. **Move to a P-series SKU + enable auto-scale-out** (multiple instances).
5. **Co-locate + tune the DB** (indexes, connection bound, read replica if needed).
6. Optional: **Channels+Redis websockets** for instant worklist push; background worker for reminders/exports.

Steps 1–2 are code; 3–5 are Azure config (Redis, SKU, scale-out, DB region). You need **both** —
the code removes per-user cost; Azure provides the horsepower.
