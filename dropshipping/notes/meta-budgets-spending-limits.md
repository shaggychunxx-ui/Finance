# Meta: budgets vs spending limits vs payment threshold vs prepaid

**For agents + humans.** Source of truth (official Meta Help):

- https://www.facebook.com/business/help/998181913623584?id=1792465934137726  
  *How Budgets, spending limits, prepaid balance limits, and your payment threshold differ*

Related Meta help:

- Budgets overview: https://www.facebook.com/business/help/214319341922580  
- Payment thresholds: https://www.facebook.com/business/help/776240779095515  
- When you are charged: https://www.facebook.com/business/help/105373712886516  

**Store context:** Basecamp and Backwoods · plan **$25/wk** (~**$3.50/day**) · ad account `act_159153097599967` · see `marketing-plan.md` + `MISSION.md` (profit → raise marketing budget).

---

## Why this matters

These four controls are **easy to confuse**. Setting a **campaign budget** does **not** set your **billing threshold**, and Meta may still apply **account-level spending limits** you did not choose. Agents must not treat “budget = $3.50/day” as the only guardrail.

---

## The four controls (plain language)

| Control | Who sets it | What it does | Agent takeaway |
|---------|-------------|--------------|----------------|
| **Budget** | Advertiser (us) | How much we **want** to spend while ads run (campaign and/or ad set) | Primary lever for Week 1: ~**$3.50/day** or weekly equivalent under **$25/wk** |
| **Spending limit** | Advertiser and/or Meta | **Hard ceiling** on spend (day / campaign / **ad account**) | Prefer an **account spending limit** aligned with weekly cap so a bad campaign can’t blow past plan |
| **Payment threshold** | **Meta** (auto) | How much unpaid ad cost can accumulate **before Meta charges** the card | **Not** a budget. Small accounts get charged often; multiple charges/month are normal |
| **Prepaid balance limit** | **Meta** (if prepaid) | Caps how prepaid credit works / max balance | Only relevant if the account uses prepaid balance, not automatic billing |

Meta’s article states you can control or set **most** of these amounts, but **Meta** sets your **daily spending limit** (in some cases) and **prepaid balance limits**.

---

## Budgets (we control)

- A **budget** is the amount of money you want to spend on ads **during their run time**.
- Set a **campaign** budget and/or **ad set** budgets.
- Two duration types (high level):
  - **Daily** — target average spend per day (can flex slightly day to day).
  - **Lifetime** — amount for the whole flight; Meta treats lifetime as a **hard cap**.
- **ShopifyDS Week 1 recipe** (`marketing-plan.md`): one Meta campaign, ~**$3.50/day**, **$25/wk** ceiling, one hero PDP only.

**Do not** raise budget because “threshold charged again” or “Meta suggested scale.” Raise only per plan, human instruction, or **profit → marketing budget** policy in `MISSION.md`.

---

## Spending limits (ceiling)

- Spending limits control the **maximum** you can spend on ads **per day, per campaign, or per ad account**.
- Use them as a **safety net above** the planned budget, not as a substitute for a sensible daily budget.
- If Meta has applied a **low daily spending limit** (new account / policy review), campaigns may under-deliver even with a correct budget — check Ads Manager billing/restrictions before “fixing” creatives.

**Agent rule:** before any automated budget change, read current account/campaign spend + any account spending limit. Never set daily budget that would exceed **remaining weekly room** under $25 (or the raised profit-backed cap).

---

## Payment threshold (billing only — not a budget)

- A **payment threshold** is how much you can spend on ads **before Meta charges** your payment method.
- When unpaid ad costs **hit the threshold**, Meta bills that amount; also billed on the **monthly bill date** if you have not hit the threshold.
- New accounts often start with a **small** threshold; successful payments can **raise** it over time.
- **Multiple charges in one month are normal** (threshold hits + monthly bill).

**Agent rules:**

- Do **not** interpret a charge as “we spent the whole weekly budget.”
- Do **not** change campaign budget because of a threshold charge.
- Do **not** tell humans that payment threshold = ad budget.
- Billing issues / failed payment → **human**; pause if required by plan, do not invent new payment methods.

---

## Prepaid balance limits

- Apply when the ad account funds ads from a **prepaid balance**.
- Meta sets **prepaid balance limits**.
- If the account uses **automatic payments** (card on file), focus on budget + spending limit + threshold instead.

---

## How they stack (example)

```text
Account spending limit (optional hard ceiling, e.g. $25–30/wk or monthly)
        │
        ▼
Campaign / ad set budget  ←  what delivery optimizes toward (~$3.50/day Week 1)
        │
        ▼
Actual spend accumulates
        │
        ├─► Payment threshold hit  →  Meta charges card (billing event)
        └─► Monthly bill date      →  Meta charges remaining unpaid amount
```

Spend can still be **below** budget (learning, low delivery, Page missing, payment fail, Meta restrictions).

---

## Basecamp and Backwoods — agent checklist

1. **First payment bootstrap (human):** Meta may show **“my first payment”** until ~**$2** of ads run and the card is charged — then login/connect can finish. **Agents do not auto-spend this.** After charge, still need creatives + Page + durable token for real Week 1.  
2. **Page required** for FB/IG identity — API previously saw **0 Pages** (still a launch blocker).  
3. Cap total Meta spend ≤ **$25/wk** until human or profit policy raises it (`MISSION.md`).  
4. Week 1: ~**$3.50/day**, hero = Zendrop water filter straw PDP only.  
5. Prefer **lifetime or daily budget** that cannot exceed weekly cap; add **account spending limit** when tooling allows.  
6. Treat **payment threshold** as billing metadata only (first charge is often a small threshold hit — expected).  
7. No agent-driven ads until: first payment done + creatives §14 + FB Page + prefer **long-lived / system-user** Marketing token (`notes/meta-marketing-api-setup-2026-07-28.md`).  
8. Never put access tokens or card details in git / STATUS.

---

## Where else this is referenced

| Doc | Role |
|-----|------|
| `notes/meta-marketing-api-setup-2026-07-28.md` | Token + IDs + blockers |
| `notes/meta-terms-of-service.md` | Meta ToS summary (https://www.facebook.com/legal/terms) |
| `notes/meta-ad-standards.md` | Ad Standards (https://transparency.meta.com/policies/ad-standards/) |
| `notes/meta-lead-ad-terms.md` | Lead Ad Terms (https://www.facebook.com/legal/leadgen/tos) |
| `marketing-plan.md` | $25/wk recipe |
| `MISSION.md` | Profit → marketing budget |
| `STATUS.md` | Live handoff |
