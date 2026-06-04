# WellNest Scribe — Data Breach Response Procedure

**Version:** 1.0 | **Date:** June 2026 | **Owner:** WellNest Operations

---

## 1. What Counts as a Breach

A personal data breach is any security incident that leads to the accidental or unlawful **destruction, loss, alteration, unauthorised disclosure of, or access to** personal data.

Examples relevant to WellNest Scribe:

| Incident | Breach? |
|----------|---------|
| Doctor's device stolen while logged in | Yes |
| Unauthorised user accesses a session via a leaked URL | Yes |
| Azure outage corrupts audio files | Possibly (assess data loss) |
| Doctor accidentally emails a note to the wrong patient | Yes |
| Doctor misidentifies a patient in a note | Yes (data accuracy) |
| SQL injection exposes session records | Yes |
| Failed login attempt (brute force, no access gained) | No |
| Doctor accidentally opens the wrong patient's session then closes it | Low risk — assess |

---

## 2. Roles

| Role | Person | Responsibility |
|------|--------|----------------|
| Data Controller | WellNest / Clinic operator | Overall accountability |
| Designated Breach Officer | TBD — assign before pilot | Receives reports, makes notification decisions |
| Technical Lead | Developer / Adrian | Investigates, preserves evidence, applies fixes |
| Legal Counsel | TBD | Advises on notification obligations |

---

## 3. Detection and Reporting

**Any** staff member, doctor, or user who suspects a breach must report it immediately to the Breach Officer. Do not attempt to investigate alone or conceal a potential breach.

Report via: [designate a channel — e.g., breach@wellnest.health or a private Slack channel]

Information to include in the initial report:
- Date/time breach was discovered
- How it was discovered
- What data may be affected (type, approximate number of records)
- Whether the breach is ongoing

The clock starts when the breach is **discovered**, not when it occurred.

---

## 4. Assessment (within 24 hours)

The Technical Lead and Breach Officer assess:

1. **Is this a notifiable breach?**
   - Likely to result in risk to rights and freedoms of individuals → **must notify regulator within 72 hours**
   - Likely to result in *high* risk → **must also notify affected individuals without undue delay**

2. **Contain the breach** — revoke tokens, disable accounts, patch vulnerability, take compromised server offline if needed.

3. **Preserve evidence** — do NOT delete logs, wipe servers, or apply patches that destroy forensic evidence before the scope is understood.

4. **Document everything** — fill in the Breach Register (Section 7) immediately, even if incomplete.

---

## 5. Notification Obligations

### 5a. Jamaica — Information Commissioner's Office (ICO Jamaica)
- **Deadline:** 72 hours from discovery (JA DPA s.27)
- **Method:** Written notification to the ICO — [confirm current notification method with ICO Jamaica]
- **Content required:**
  - Nature of the breach
  - Categories and approximate number of data subjects affected
  - Categories and approximate number of records affected
  - Name and contact details of the Data Protection Officer / contact point
  - Likely consequences of the breach
  - Measures taken or proposed to address the breach

### 5b. Barbados — Data Protection Commissioner
- **Deadline:** 72 hours (BB DPA s.24)
- **Method:** Written notification — [confirm with DPC Barbados]
- Same content as Jamaica above

### 5c. Affected individuals
- Required when the breach is **likely to result in high risk** to individuals
- Must be in plain language
- Must describe: nature of breach, likely consequences, measures taken, contact point for further information
- **No notification required** if the data was encrypted, or if notification would require disproportionate effort (in which case a public communication may substitute)

---

## 6. Post-Breach Actions

1. **Root cause analysis** — document what failed and why
2. **Patch / fix** — deploy fix and verify before bringing services back online
3. **Update audit log** — `audit.log` must record the breach detection, containment, and remediation timestamps
4. **DPIA update** — if the breach reveals a gap in the DPIA, update it
5. **Staff briefing** — notify doctors affected; provide guidance
6. **Review and update** this procedure if gaps were identified

---

## 7. Breach Register Template

Maintain a running register. Each entry must contain:

```
Breach ID:          [sequential — e.g., BR-2026-001]
Date discovered:    
Date occurred (if known):
Reported by:        
Data subjects affected (type):
Approximate number of subjects:
Data categories affected:
Cause:              
Containment actions taken:
Regulator notified? [Y/N]  Date:
Individuals notified? [Y/N] Date:
Outcome / lessons learned:
Closed date:
```

Store the register in a secure, access-controlled location — not in the application database.

---

## 8. WellNest-Specific Indicators to Monitor

The following `audit.log` events should trigger an automated alert (e.g., email to Breach Officer) if they occur:

| Event | Threshold | Action |
|-------|-----------|--------|
| `sensitive_viewed` by non-owner | Any | Investigate immediately |
| `share_blocked` for sensitive session | > 3 in 1 hour | Check for automated scraping |
| `session_deleted` | Any | Verify it was patient-requested |
| Failed login attempts | > 10 in 5 min | Likely brute force — consider temporary lockout |
| `sensitive_flag_changed` | Any | Verify doctor intent |

---

*Review this procedure annually and after any incident. Keep a signed-off copy with the clinic's compliance file.*
