# WellNest — Roles, Subscriptions & Access Control (design + reference)

**Status:** design proposal + current-state reference · **Date:** 2026-07-16 ·
**Purpose:** define one coherent role model, plan-based feature gating, and the
Wellness-vs-clinic admin split, then enforce them server-side. This is the
"who can see/do what" reference, and the plan we implement against.

---

## 1. The core problem today

There are **two parallel role systems** that overlap and can drift apart:

- `DoctorProfile.role` (platform): clinician, lead, admin, scribe, ed_nurse,
  nurse, receptionist, radiologist, pharmacist, lab_tech
  (`apps/accounts/models.py`). Drives `can_use_scribe()`, `can_finalize()`, etc.
- `OrganisationMembership.role` (per-org): doctor, nurse, receptionist, scribe,
  radiologist, pharmacist, lab_tech, admin, system_admin
  (`apps/emr/models.py`). Drives `can_register_patients()`,
  `can_edit_encounters()`, etc.

**Consequences (the bugs you hit):**
- Demoting a user's *org membership* to nurse does **not** remove Scribe, because
  Scribe is gated by the *platform* role, which didn't change. → the nurse can
  still record.
- The Scribe **"New session" page and `create_session_api` have no server-side
  role gate** — only the button is hidden. A nurse can reach it by URL.
- `subscription_tier` exists but is **never used to gate EMR** — a Scribe-only
  clinic still sees Appointments, Register patient, Worklist, etc.
- **Every user auto-gets their own "{name}'s Clinic"** (`ensure_default_membership`)
  — that's why Users & Orgs is a mess of one-person clinics.
- **Org admin = the doctor**, and org admins can reach billing-adjacent screens.
  There is no clean isolation between the **Wellness team** (us) and the **clinic
  owner**.

## 2. Proposed model — one role per (user, org)

**Single source of truth: `OrganisationMembership.role`.** Platform capabilities
(Scribe, finalize, ED board) are *derived from that role*, not from a second
field. `DoctorProfile.role` is demoted to a display/default hint only (or removed
after migration). This makes "demote to nurse" actually remove scribe everywhere,
because there is only one role to change.

**Two axes of access, kept separate:**
1. **Role** — what a person *does* (clinical function). Set per org.
2. **Plan** — what the *clinic paid for* (feature entitlement). Set per org by
   Wellness.

A capability is allowed only if **role permits it AND the plan includes it.**

## 3. Role catalogue + access matrix

Roles (per org). "Scribe" column = AI note capture; "EMR" columns require an EMR
plan (see §4).

| Role | Scribe record/finalize | View charts / encounters | Edit/sign encounters | Register patient / schedule | Manage clinic settings | Manage plan / seats / roles |
|---|---|---|---|---|---|---|
| **Doctor / Clinician** | ✅ | ✅ | ✅ (sign) | ✅ | — | — |
| **Clinic Lead** (head of clinic) | ✅ | ✅ | ✅ (sign) | ✅ | ✅ (settings, members view) | view-only plan |
| **Nurse** | ❌ (no record) | ✅ | edit only, no sign | ✅ | — | — |
| **ED Nurse** | ❌ | ✅ (ED board/triage) | edit only | ✅ | — | — |
| **Receptionist** | ❌ | read-only | ❌ | ✅ (register/schedule) | — | — |
| **Scribe (medical scribe)** | ✅ record, ❌ finalize | ✅ | ❌ | — | — | — |
| **Radiologist** | ❌ | ✅ imaging | report only | — | — | — |
| **Pharmacist** | ❌ | meds view | meds only | — | — | — |
| **Lab tech** | ❌ | labs view | labs only | — | — | — |
| **Wellness Super-Admin** (us) | ✅ all | ✅ all | ✅ all | ✅ all | ✅ all orgs | ✅ all orgs |

Notes:
- **Nurse does NOT get Scribe** (your call). If a nurse must fill in for a doctor,
  that's a temporary role change by a Lead/Wellness, not a default.
- **Clinic Lead** is the new "head of clinic" role: manages their own clinic's
  settings and can *see* the plan, but **cannot change plan, seats, or roles** —
  that's Wellness-only.
- **Doctor is never an org/system admin by default.**

## 4. Plan / subscription model

Tiers (`SUBSCRIPTION_TIER_CHOICES`, extend as needed):

| Plan | Scribe | EMR (charts, encounters, appointments, register) | Price |
|---|---|---|---|
| **Trial** | ✅ | ✅ (time-limited) | — |
| **Scribe only** | ✅ | ❌ hidden | $94 |
| **Scribe + EMR (Practice)** | ✅ | ✅ | $144 |
| **Professional** | ✅ (higher caps) | ❌ | $190 |
| **Professional + EMR** | ✅ | ✅ | $240 |

**Gating rules:**
- **`org.has_emr`** (new): plan is one of the EMR-bearing tiers. Gates all EMR nav
  and views (Appointments, Register patient, Worklist, Find patient chart edit,
  encounter editor). A Scribe-only clinic sees **only** Scribe + its own sessions.
- **`org.scribe_enabled`** (exists): scribe note generation. Off when
  suspended/cancelled. Already implemented.
- **Suspension ≠ data loss.** Suspending pauses Scribe; **EMR records stay
  readable** (patient safety — already the rule). 
- **Downgrades that remove EMR are BLOCKED (decided).** A clinic on an EMR plan
  cannot self-downgrade to a Scribe-only plan — that would strip access to medical
  records they created, which is a patient-safety and data-access risk and is not
  standard practice for medical records. Stated plainly in the plan FAQ. To leave
  EMR they contact Wellness (export + managed offboarding, records preserved).
- **Upgrades are always seamless & instant:** Scribe-only → Scribe+EMR (any
  level), and Scribe+EMR → a higher-cost Scribe+EMR tier. No data migration; EMR
  switches on / caps rise immediately.
- **Same-family scribe changes** (Standard ↔ Professional, both without EMR, or
  both with EMR) are allowed — they change note caps only, not record access.
- Only Wellness changes plans.

### 4.1 Plan-change FAQ (for the in-app FAQ / support)

- **Can I upgrade any time?** Yes. Upgrades (to EMR, or to a higher tier) apply
  immediately with no data migration and nothing to re-enter.
- **Can I drop EMR and keep only Scribe?** No — not self-serve. Once a clinic has
  an EMR record system, we don't strip access to existing patient records (safety
  + record-keeping obligations). Contact WellNest to offboard; your data is
  exported and preserved, never silently deleted.
- **What if I stop paying?** Scribe (AI notes) pauses; your **existing EMR records
  stay readable** so patient care is never blocked. Nothing is deleted.
- **Can I switch Standard ↔ Professional?** Yes — that only changes your monthly
  note allowance, not record access.

## 5. Wellness super-admin vs clinic owner (isolation)

- **Wellness Super-Admin = Django `is_staff`/`is_superuser`.** This is *us*. Only
  Wellness can: create orgs, assign/leave plans, set seats, set roles, record
  payments, suspend/downgrade. Billing + Users&Orgs plan editing = Wellness-only.
- **Clinic Lead** (org role) can: view their plan/seats/paid-through (read-only),
  edit clinic profile/settings, and *see* their members — but **not** change
  roles or plan. To change a plan they contact Wellness (a "Contact WellNest"
  action that logs a request, replacing the broken "Get started" mailto).
- **Org "admin"/"system_admin" membership roles are retired** for clinics — the
  only cross-org admin is Wellness. (Keeps the boundary clean.)

## 6. Signup & org creation fix

- At signup a user **picks their role** (kept — you want easy testing) and either
  **joins an existing facility** (searchable) or requests a new one.
- **Stop auto-creating a solo "{name}'s Clinic" for everyone.** Instead: a user
  with no org lands in a "no clinic yet — ask your admin / Wellness to add you"
  state (Scribe can still work as a personal workspace if that's desired).
- **Role is locked after signup** — only a Lead (within limits) or Wellness can
  change it. (Largely true today; enforce it.)

## 7. Enforcement architecture (server-side, not just hidden buttons)

1. **Capability helpers** — one place: `membership.can_scribe()`,
   `.can_finalize()`, `.can_edit_encounters()`, `.can_manage_clinic()`,
   `.can_manage_billing()` — each checks **role AND plan**.
2. **Middleware** — an `AccessGateMiddleware` that maps URL prefixes to required
   capabilities (e.g. `/emr/appointments*` → `has_emr`; `/scribe/record*` →
   `can_scribe`) and returns 403/redirect for the unentitled. This is the
   backstop so a hidden button can never be bypassed by URL.
3. **View gates** — keep `_require(...)` on sensitive views, now using the unified
   helpers.
4. **Nav/template gates** — show/hide by the same helpers (via context
   processor), so the UI matches what the server enforces.
5. **A `/roles` reference page** — an in-app page (this matrix) so any admin can
   see who can do what.

## 8. Manual subscription management (until card payments)

Wellness billing page (tidied): search an org → set plan, seats, status,
paid-through, monthly amount, and **record a payment** ("paid 5 months from
2026-07-16" → sets paid-through and logs it). A daily job flips orgs past their
paid-through to `past_due` → later `suspended` (scribe off, EMR read-only). Export
invoices/receipts. All Wellness-only.

## 9. Phased implementation

- **P1 (safety-critical):** server-side gate the Scribe New-session page +
  `create_session_api` by `can_scribe`; unify the scribe check so a nurse role
  truly cannot record; hide Record-visit for non-scribe roles (already hidden,
  make it real).
- **P2:** `org.has_emr` + gate EMR nav/views + read-only downgrade; middleware
  backstop.
- **P3:** unify to one role source; retire `DoctorProfile.role` as the gate;
  Clinic Lead role; lock role after signup; stop auto-solo-clinic.
- **P4:** Wellness billing/subscription management tidy-up + payments + auto
  expiry; `/roles` in-app page; "Contact WellNest" request flow.

Each phase is shippable and independently testable. P1 closes the immediate
"nurse can still record" hole.

---

## 10. Implemented so far — how enforcement works today (P1)

**Scribe (recording) is now gated by the org membership role, server-side.**

- **Authoritative check:** `OrganisationMembership.can_scribe()`
  (`apps/emr/models.py`) → allowed for `doctor, scribe, admin, system_admin`;
  denied for `nurse, receptionist, pharmacist, lab_tech, radiologist`. Django
  `is_staff`/`is_superuser` bypass everything (that's the Wellness team).
- **Four enforcement points** (a hidden button is never the enforcement):
  1. Nav — `templates/partials/_nav_items.html` wraps New session + Sessions in
     `{% if can_scribe %}`.
  2. Record-visit buttons — `patient_search.html`, `patient_detail.html` gate on
     `can_scribe`.
  3. Page — `RecordView.get` (`apps/scribe/views.py`) redirects a non-scribe role
     away, even by direct URL.
  4. API — `create_session_api` returns 403 for a non-scribe role.
- **Where `can_scribe` comes from in templates:** the context processor
  (`apps/scribe/context_processors.py`) sets it from
  `get_membership(user).membership.can_scribe()`.

**GOTCHA (cost us a bug):** `get_membership(user)` returns an **`EMRContext`**
dataclass, not a membership. You must call
`get_membership(user).membership.can_scribe()`. Calling `.can_scribe()` directly
on the context raises `AttributeError`, which a broad `except` will silently
swallow and fall through to a permissive default — i.e. the gate looks present but
never fires. Always go through `.membership`.

**How to add a new capability gate (pattern to follow):**
1. Add `can_x()` to `OrganisationMembership` (role list + `_django_privileged`).
2. Enforce it in the view/API (`get_membership(request.user).membership.can_x()`),
   returning 403/redirect.
3. Expose it in the context processor and gate the nav/buttons on it.
4. (P2+) the `AccessGateMiddleware` will map URL prefixes → capability as a
   backstop so no gate can be bypassed by URL.

**Testing note:** a Django `is_staff`/superuser account bypasses every gate by
design. To test a role gate, use a **non-staff** account with that membership role.

## 11. Backlog parked here (so it isn't lost)

- **Check-in abuse / fake emergencies** (Sean's feature): a public check-in could
  be spammed with fake/prank "emergency" entries, so arrivals don't match reality.
  Mitigations to build with it: check-ins are **unverified "pending"** until a
  human verifies identity on arrival (they never auto-create a confirmed record);
  **rate-limit + captcha** the public endpoint; optionally require a
  **clinic-provided code / waiting-room QR** so only people actually at/heading to
  that clinic can check in; the emergency option flags priority but still requires
  on-arrival verification and exposes no PHI.
