# WellNest — Documentation

Start with **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — its §0 *Current Stack Summary* is the
fastest accurate picture of what runs in production right now.

Everything else is organised by topic below (nothing here is deleted — just filed).

## `architecture/` — system design & workflows
- `pipeline_architecture.md` — audio → interpret → SOAP generation pipeline
- `speech_pipeline.html` — pipeline visual
- `clinical_workflow.md` — end-to-end clinical workflow
- `ED_WORKFLOW_PLAN.md` — Emergency Department module design
- `TRYTON_ARCHITECTURE.md` — GNU Health / Tryton EMR bridge

## `finance/` — measured cost, the financial model & how the subscription works
- `Subscription_and_Usage_System.md` — **how the whole subscription/usage system works right now**: plans, note-credits, every user limit/safeguard, edge cases, FAQ, code map + a paste-to-AI audit prompt
- `Control_Test_2026-07.md` — the measured AI-cost control test (raw evidence log)
- `July_2026_Financials_Estimate.md` — per-note cost derivation
- `_wellnest_financials.py` — runnable, self-checking financial model (all numbers assert)
- `build_business_plan.py` — generates the business-plan `.docx` from the model

## `business/` — plan, pricing, market
- `WellNest_Business_Plan.docx` — the consolidated plan (Parts A–F: plan · working · validation · usage model · changes · terms)
- `business_model.md`, `billing_policy.md`
- `competitor_analysis.md` / `.docx` / `_v2.docx`
- `WellNest_Scribe_Business_Model.docx`

## `security/`
- `security.md`, `data_security_policy.md`, `azure_key_management.md`

## `operations/` — server / runtime config
- `server_and_gunicorn.md` — the Gunicorn worker fix (**sync → gthread**, more workers/threads) that ended the site-wide freeze; capacity, Startup Command, and how to verify it's live

## `setup/` — provisioning & environment
- `omni_asr_modal_setup.md`, `omni_asr_wsl2_setup.md`, `omni_asr_colab_demo.ipynb`

## `research/`
- `caribbean_creoles_research.md`

## `roadmap/` — forward plans
- `scaling_architecture.md` — the queue → short-polling change + expected scale (current state → path to thousands)
- `performance_optimization_ideas.md`
- `feature_bucket_list.md`
- `multispecialty_and_documents_architecture.md`

## `planning/`
- `BUILD_PLAN_2026-07.md`
