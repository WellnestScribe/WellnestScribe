# WellNest Scribe — Business Model & Financial Projections

> Internal reference. Exchange rate used throughout: **160 JMD = $1 USD** (approximate).

---

## Pricing Tiers

| Plan | Price | Who it's for |
|------|-------|-------------|
| AI Scribe only | **15,000 JMD/clinician/month** | Solo doctors, small practices |
| AI Scribe + EHR + Backup + Priority updates | **30,000 JMD/clinician/month** | Practices wanting full stack |
| Institution bundle (5+ doctors) | **20% discount off per-clinician rate** | Clinics, hospitals |

### Institution bundle example
5 doctors × 15,000 JMD = 75,000 → **20% off = 60,000 JMD/month**

Push the AI Scribe + EHR tier where possible — same infrastructure cost, double the revenue, margins hit 80%+.

---

## Infrastructure Cost Per Month

Costs are mostly USD (Modal GPU, hosting, database, Azure AI). They scale sub-linearly — fixed overhead amortises across more doctors.

| Doctors | Total tech cost | Per clinician |
|---------|----------------|---------------|
| 10 | ~$350 USD (~56,000 JMD) | ~$35 (~5,600 JMD) |
| 20 | ~$720 USD (~115,000 JMD) | ~$36 (~5,760 JMD) |
| 50 | ~$1,400 USD (~224,000 JMD) | ~$28 (~4,480 JMD) |
| 100 | ~$2,500 USD (~400,000 JMD) | ~$25 (~4,000 JMD) |

### Cost breakdown (at 20 doctors)

| Service | Monthly (USD) | Notes |
|---------|--------------|-------|
| Modal L4 GPU (omniASR transcription) | $130–260 | Per-second billing, scales with usage |
| GPT-5 generation (SOAP notes) | $300–400 | $1.25/1M input, $10/1M output |
| Render hosting (Django app) | $25–85 | Standard–Pro tier |
| Aiven MySQL database | $50–100 | HA, backups, HIPAA-adjacent |
| Azure misc (Face API, Search, Language) | $30–60 | Identity, search, NLP |
| **Total** | **$535–905** | |

---

## Profit at AI Scribe Tier (15,000 JMD/clinician)

| Doctors | Revenue | Tech cost | Gross profit | Margin |
|---------|---------|-----------|-------------|--------|
| 10 | 150,000 JMD | ~56,000 JMD | ~94,000 JMD | 63% |
| 20 | 300,000 JMD | ~115,000 JMD | ~185,000 JMD | 62% |
| 50 | 750,000 JMD | ~224,000 JMD | ~526,000 JMD | 70% |
| 100 | 1,500,000 JMD | ~400,000 JMD | ~1,100,000 JMD | 73% |

---

## Founder Pay (50/50 split)

Recommended: keep **20% of gross profit** for the business, split **80% between two founders**.

| Doctors | Gross profit | Reinvest 20% | Each founder/month |
|---------|-------------|--------------|-------------------|
| 10 | 94,000 JMD | 18,800 JMD | ~37,600 JMD |
| 20 | 185,000 JMD | 37,000 JMD | ~74,000 JMD |
| 50 | 526,000 JMD | 105,200 JMD | ~210,400 JMD |
| 100 | 1,100,000 JMD | 220,000 JMD | ~440,000 JMD |

---

## Hiring Plan

Hire from profit — the business budget comes out before founder split.

| Stage | Doctors | Gross profit | Suggested split |
|-------|---------|-------------|-----------------|
| Just the two founders | 10–20 | 94–185k JMD | 80% founders / 20% business |
| First external hire | 30–50 | 280–526k JMD | 50% founders / 50% business |
| Small team | 75–100 | 750k–1.1M JMD | 40% founders / 60% business |

### Sample team budget at 100 doctors (60% business = 660,000 JMD)

| Role | Monthly cost |
|------|-------------|
| Junior dev / support person | 120,000 JMD |
| Accountant (part-time) | 50,000 JMD |
| Marketing / sales | 80,000 JMD |
| Legal / compliance | 40,000 JMD |
| Buffer / reinvestment | 370,000 JMD |
| **Total** | **660,000 JMD** |

Each founder still takes home **~220,000 JMD/month** at this stage.

---

## Growth Roadmap

1. **0–20 doctors** — just the two founders, all hands on deck, bank the money
2. **20–40 doctors** — part-time accountant + sales person on **commission only** (10–15% of deals they close — zero fixed cost until they deliver)
3. **40–80 doctors** — first full-time hire (support/onboarding), freeing founders to focus on product
4. **80–100+ doctors** — proper small team, structured salaries

> **Key principle:** Don't hire on a fixed salary until the recurring revenue comfortably covers it for 3 months running. Use commission-only sales first — zero risk, they only earn when you grow.

---

## GPU & Concurrency Notes (Modal)

- **Best GPU**: L4 at $0.000222/sec — cheapest *per job* despite not being cheapest per second, because it's 3.7× faster than T4
- **Concurrent users**: each request spins its own container on its own L4 — 10 simultaneous doctors = 10 parallel containers, billed per second each
- **Recommended Modal config**:
  ```python
  @app.function(
      gpu="L4",
      container_idle_timeout=120,  # stays warm 2 min after last request
      max_containers=15,           # caps spend during unexpected spikes
  )
  ```
- **Cold start**: ~40s on first call after container scales to zero; warm runs ~17s inference for a 5-min consult
- At 20+ active doctors, containers stay warm naturally during business hours — cold starts only happen at the very start of the day

---

## Unit Economics Summary

| Metric | Value |
|--------|-------|
| Revenue per clinician (basic) | 15,000 JMD/mo |
| Cost to serve one clinician | ~5,600–5,800 JMD/mo |
| Gross margin per clinician | ~62–63% |
| Break-even (covering founder salaries) | ~15–20 doctors |
| Target headcount for comfortable hiring | 40–50 doctors |
