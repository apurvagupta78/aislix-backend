# Financial Model

Financial analytics are **auditable models**, not generated prose. Every result shows currency, period, perspective, price basis, input sources, estimate mode, assumptions, and missing prerequisites.

**Estimate modes:** `observed` | `calculated` | `modeled` | `scenario` | `measured`

---

## Core symbols

For SKU *i*:

- λᵢ — unconstrained demand (sellable units / time)
- dᵢ — unserved demand fraction (from evidence or labeled scenario)
- pᵢ — selling price (consistent tax basis)
- cᵢ — unit cost; mᵢ — unit contribution
- H — explicit time window

**Unserved demand:** Dᵢ = λᵢ × H × dᵢ (constant-rate approximation)

---

## 1. Gross SKU sales exposure

**Formula:** Dᵢ × pᵢ  
**Label when only MRP available:** “MRP-valued demand exposure”  
**Not:** Actual revenue loss, net profit, or manufacturer realization.

**Screenshot-permitted illustration (conditional):**

- Daily sales 5 × MRP ₹100 = **₹500/day** IF full-day unavailability scenario assumed.  
- **Not justified from photo alone:** actual loss, recovered revenue, profit, 3-day cover from expected qty 15.

---

## 2. Substitution-adjusted retail impact

**Net revenue:** Dᵢ × pᵢ − Σⱼ Uᵢⱼ × pⱼ  
**Net contribution:** Dᵢ × mᵢ − Σⱼ Uᵢⱼ × mⱼ  

Disclose retention/substitution assumptions. Negative net loss (substitution gain) is valid — do not clamp silently.

---

## 3. Synthetic regression fixture

| Input | Value |
|-------|-------|
| Net selling price | ₹100 |
| Demand | 5 units/day |
| Scenario | Full-day absence |
| Retention | 50% same-price substitutes |
| Unit contribution (original & sub) | ₹20 |

| Output | Amount | Mode |
|--------|--------|------|
| Gross SKU sales exposure | ₹500 | scenario |
| Net retailer revenue impact | ₹250 | scenario |
| Net contribution impact | ₹50 | scenario |

**Do not sum these three** — they are related views of one scenario.

**Test:** `test_max_fresh_oos_revenue_at_risk_uses_velocity_not_expected_qty`

---

## 4. Manufacturer exposure

Distinguish switching to same-brand SKU, competitor, other retailer, or abandoned purchase.  
Retail sell-through × net realization = demand-equivalent scenario unless sell-in link established.

---

## 5. Recoverable opportunity

**Net action benefit** = incremental contribution from fix − incremental action costs  
Recoverable demand ≤ modeled addressable unserved demand.  
Restored facings ≠ recovered sales until verified over time.

---

## 6. Value-weighted availability

Σ(λᵢ × pᵢ × availabilityᵢ) / Σ(λᵢ × pᵢ) — modeled, not actual sales protected.

---

## 7. Inventory cover

**Requires verified inventory**, not photo facings.  
Days of cover = available units / daily demand.  
Expected quantity 15 ≠ current on-hand 15.

---

## 8. Non-double-counting

Ledger key: tenant + store + bay/SKU + interval + root cause.

One absence → one commercial event. Do not charge as planogram gap + OOS + placement + gross + net simultaneously.

Rank by **marginal** benefit, not independent sums.

---

## 9. Customer ROI

- B = attributable incremental contribution + realized savings  
- C = subscription + implementation + incremental ops costs  
- ROI = (B − C) / C  
- Payback, NPV with disclosed discount rate  
- Verified outcomes: difference-in-differences preferred over simple before/after

Before/after photos verify **physical** execution, not sales causality.

---

## 10. UI rules

- Badge: Scenario / Modeled / Measured  
- Missing inputs → “Add selling price and demand horizon” not “Commercial risk: High” alone  
- Financial impact column: **₹X–Y over N days** or **Not estimated**  
- Never multiply model confidence as lost-sales probability

**Implementation:** `app/metrics.py::compute_financial_impact` (extend toward full contract)
