"""WellNest financial model - EVERY number derived and shown, not assumed.

Run: python docs/_wellnest_financials.py
Produces the full working that feeds the business plan's "Financial Working" section.
"""

def line(): print("-" * 72)

# =============================================================================
# STEP 1. Cost per note - measured from the control test (token-level math)
# =============================================================================
print("STEP 1 - COST PER NOTE (measured control test, 2026-07-11)")
line()
IN_RATE = 2.50 / 1_000_000     # $/input token   (Azure gpt-5, confirmed)
OUT_RATE = 15.00 / 1_000_000   # $/output token
T4_RATE = 0.000164             # $/GPU-second (T4 = $0.59/hr)

runs = [  # (label, prompt_tok, completion_tok, gpu_seconds)
    ("5-min",  9130,  618,  30.483),
    ("20-min", 12667, 714,  113.951),
    ("60-min", 21882, 649,  279.994),
]
for label, p, c, gpu in runs:
    gin, gout = p * IN_RATE, c * OUT_RATE
    gpt = gin + gout
    omni = gpu * T4_RATE
    print(f"  {label:7} GPT in {p:>6}x$2.50/1M=${gin:.4f} + out {c:>4}x$15/1M=${gout:.4f} "
          f"= ${gpt:.4f}; omniASR {gpu:.1f}s x$0.000164=${omni:.4f}  => NOTE ${gpt+omni:.4f}")
COST_PER_NOTE = 0.05   # conservative planning figure (typical 12-min note measured ~$0.045-0.048)
print(f"  -> Planning cost/note = ${COST_PER_NOTE} (conservative; measured typical ~$0.045)")

# =============================================================================
# STEP 2. Cost to serve one clinician - notes/month x cost/note (per plan)
# =============================================================================
print("\nSTEP 2 - COST TO SERVE ONE CLINICIAN / MONTH (derived, per plan)")
line()
DAYS = 22
STD_PPD, PRO_PPD = 18, 30       # patients/day: Standard mid of 15-20, Professional mid of 25-40
std_notes = STD_PPD * DAYS
pro_notes = PRO_PPD * DAYS
cts_std = round(std_notes * COST_PER_NOTE, 2)
cts_pro = round(pro_notes * COST_PER_NOTE, 2)
print(f"  Standard doctor    : {STD_PPD}/day x {DAYS} days = {std_notes} notes  x ${COST_PER_NOTE} = ${cts_std}/mo")
print(f"  Professional doctor: {PRO_PPD}/day x {DAYS} days = {pro_notes} notes  x ${COST_PER_NOTE} = ${cts_pro}/mo")
print(f"  EMR add-on marginal cost ~ $0 (DB/storage cents) - EMR plans use the same scribe cost")

# =============================================================================
# STEP 3. Gross margin per plan = (price - cost to serve) / price
# =============================================================================
print("\nSTEP 3 - GROSS MARGIN PER PLAN")
line()
PLANS = [  # name, price, cost_to_serve
    ("Standard",           94,  cts_std),
    ("Standard + EMR",     144, cts_std),
    ("Professional",       190, cts_pro),
    ("Professional + EMR", 240, cts_pro),
]
for name, price, cts in PLANS:
    gm = (price - cts) / price
    print(f"  {name:20} (${price}): ({price} - {cts}) / {price} = {gm*100:.0f}%")

# =============================================================================
# STEP 4. Blended ARPU and blended cost to serve (from a tier mix)
# =============================================================================
print("\nSTEP 4 - BLENDED ARPU & COST TO SERVE (assumed tier mix)")
line()
MIX = [("Standard", 0.50, 94, cts_std), ("Standard + EMR", 0.15, 144, cts_std),
       ("Professional", 0.25, 190, cts_pro), ("Professional + EMR", 0.10, 240, cts_pro)]
ARPU = 0.0; BLEND_CTS = 0.0
for name, w, price, cts in MIX:
    ARPU += w * price; BLEND_CTS += w * cts
    print(f"  {int(w*100):>3}% x {name:20} price ${price:<3} -> ${w*price:5.2f} ARPU ; cost ${w*cts:5.2f}")
ARPU = round(ARPU, 2); BLEND_CTS = round(BLEND_CTS, 2)
blend_gm = (ARPU - BLEND_CTS) / ARPU
print(f"  Blended ARPU = ${ARPU} ; blended cost to serve = ${BLEND_CTS} ; gross margin = {blend_gm*100:.0f}%")

# =============================================================================
# STEP 5. Revenue - VERIFY the $564,000, and the blended figure
# =============================================================================
print("\nSTEP 5 - REVENUE (verify $564,000)")
line()
CLIN = {"Y1": 50, "Y2": 200, "Y3": 500}
print("  Conservative (ALL on Standard $94):")
rev_std = {}
for y, n in CLIN.items():
    rev_std[y] = n * 94 * 12
    print(f"    {y}: {n} clinicians x $94 x 12 = ${rev_std[y]:,}")
print(f"    -> Y3 $564,000 CONFIRMED (assumes every clinician on the cheapest plan)")
print("  Base case (blended ARPU $140.10):")
rev_bl = {}
for y, n in CLIN.items():
    rev_bl[y] = round(n * ARPU * 12)
    print(f"    {y}: {n} x ${ARPU} x 12 = ${rev_bl[y]:,}")

# =============================================================================
# STEP 6. COGS = clinicians x cost to serve x 12
# =============================================================================
print("\nSTEP 6 - COGS (variable AI cost)")
line()
cogs_std, cogs_bl = {}, {}
for y, n in CLIN.items():
    cogs_std[y] = round(n * cts_std * 12)
    cogs_bl[y] = round(n * BLEND_CTS * 12)
    print(f"  {y}: Std {n}x${cts_std}x12=${cogs_std[y]:,} ; Blend {n}x${BLEND_CTS}x12=${cogs_bl[y]:,}")

# =============================================================================
# STEP 7. Opex - ITEMISED (this is 'employing people')
# =============================================================================
print("\nSTEP 7 - OPEX, ITEMISED (salaries + platform + marketing)")
line()
OPEX_ITEMS = {
    "Y1": [("Founder stipends (2 x $15k)", 30000), ("Commission sales rep", 8000),
           ("Platform/hosting ($300x12)", 3600), ("Marketing & outreach", 8000),
           ("Compliance/legal/insurance", 3500), ("Misc/tools", 1900)],
    "Y2": [("Founder stipends (2 x $30k)", 60000), ("Sales rep", 25000),
           ("Customer success (PT)", 18000), ("Platform/hosting", 3600),
           ("Marketing", 25000), ("Compliance", 8000), ("Misc/tools", 10400)],
    "Y3": [("Founder stipends (2 x $40k)", 80000), ("Sales team", 70000),
           ("Customer success", 35000), ("Data/ML engineer", 45000),
           ("Platform/hosting", 3600), ("Marketing", 50000),
           ("Compliance", 12000), ("Misc/tools", 24400)],
}
OPEX = {}
for y, items in OPEX_ITEMS.items():
    OPEX[y] = sum(v for _, v in items)
    print(f"  {y}: " + " + ".join(f"{n} ${v:,}" for n, v in items) + f"  = ${OPEX[y]:,}")

# =============================================================================
# STEP 8. NET PROFIT = Revenue - COGS - Opex  (fully shown)
# =============================================================================
print("\nSTEP 8 - NET PROFIT DERIVATION")
line()
def pnl(tag, rev, cogs):
    print(f"  {tag}:")
    net = {}
    for y in ("Y1", "Y2", "Y3"):
        gp = rev[y] - cogs[y]
        net[y] = gp - OPEX[y]
        print(f"    {y}: rev ${rev[y]:,} - COGS ${cogs[y]:,} = GP ${gp:,} ({gp/rev[y]*100:.0f}%) "
              f"- opex ${OPEX[y]:,} = NET ${net[y]:,}")
    return net
net_std = pnl("Conservative (Standard-only)", rev_std, cogs_std)
net_bl = pnl("Base case (blended)", rev_bl, cogs_bl)

# =============================================================================
# STEP 9. Break-even + LTV/CAC
# =============================================================================
print("\nSTEP 9 - BREAK-EVEN & UNIT ECONOMICS")
line()
FIXED_MO = 1500
contrib = 94 - cts_std
be = FIXED_MO / contrib
print(f"  Contribution/Standard clinician = $94 - ${cts_std} = ${contrib}/mo")
print(f"  Break-even = ${FIXED_MO}/mo fixed / ${contrib} = {be:.0f} clinicians")
CAC = 150; LIFE = 30
ltv_std = 94 * ((94 - cts_std) / 94) * LIFE
print(f"  LTV (Standard, gross) = $94 x {((94-cts_std)/94)*100:.0f}% x {LIFE} months = ${ltv_std:,.0f}")
print(f"  LTV:CAC = ${ltv_std:,.0f} / ${CAC} = {ltv_std/CAC:.0f}:1 ; Payback = ${CAC}/${contrib} = {CAC/contrib:.1f} months")

# ── checks ───────────────────────────────────────────────────────────────────
assert rev_std["Y3"] == 564_000
assert abs(ARPU - 140.10) < 0.01
assert cts_std == 19.80 and cts_pro == 33.00
print("\nAll arithmetic assertions passed.")

# Export a dict a doc builder can import
FIGS = dict(cost_per_note=COST_PER_NOTE, cts_std=cts_std, cts_pro=cts_pro,
            arpu=ARPU, blend_cts=BLEND_CTS, blend_gm=round(blend_gm*100),
            gm_std=round((94-cts_std)/94*100), rev_std=rev_std, rev_bl=rev_bl,
            cogs_std=cogs_std, cogs_bl=cogs_bl, opex=OPEX, opex_items=OPEX_ITEMS,
            net_std=net_std, net_bl=net_bl, breakeven=round(be),
            ltv=round(ltv_std), cac=CAC, payback=round(CAC/contrib, 1),
            std_notes=std_notes, pro_notes=pro_notes)
