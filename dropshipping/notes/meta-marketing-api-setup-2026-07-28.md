# Meta Marketing API setup (2026-07-28)

**Machine:** AI-CODING  
**Scope:** Store PHONE-pasted Graph/Marketing access token; validate; do **not** launch ads.

## Local files (never git)

| Path | Purpose |
|------|---------|
| `~\.meta-link\marketing-api-token` | User access token |
| `~\.meta-link\marketing-api-meta.txt` | Non-secret IDs + validation notes |
| `~\.meta-link\model-api-key` | Separate LLM Model API key |
| `~\.meta-link\pixel-id` | Storefront pixel `1911518699818229` |

## Validation summary

- Token **valid** with `ads_management` + `ads_read` + `business_management`.
- Ad account: **`act_159153097599967`** (ACTIVE, USD, $0 spent).
- Business: **`1372274451535449`**.
- Ad-account pixel: **`1162308407189446`** (name: BascampBackwoods).
- Storefront / Shopify channel pixel: **`1911518699818229`** (already live on site).
- **Pages:** none returned for user or business owned/client pages.
- **Expiry:** short-lived USER token (~**2026-07-29** local midnight). Prefer a long-lived or **system user** token before any agent ad automation.

## Still blocked for Week 1 paid ads

0. **First payment / “my first payment” (HUMAN, 2026-07-29):** Meta login/connect is waiting on the account’s **first billing charge**. Human will run about **$2** of ads so Meta can charge the card; after that charge, finish connect. **Agents must not auto-run this spend.** This is the payment-threshold bootstrap (see `notes/meta-budgets-spending-limits.md`) — not the full $25/wk campaign.  
1. **Shoot creatives** (plan §14 A/B/C) — human or BOXONE explainer task.  
2. **Facebook Page** linked to Business Manager (0 pages seen via API).  
3. **Durable token** (rotate; current one was pasted into STATUS/git — rotate).  
4. Optional: confirm which pixel Ads Manager should optimize on (storefront vs BM).

## Budgets / spend controls (agents)

Do **not** confuse campaign budget, account spending limit, payment threshold, and prepaid limits.

- Agent summary: **`notes/meta-budgets-spending-limits.md`**
- Official Meta help: https://www.facebook.com/business/help/998181913623584?id=1792465934137726  
  (*How Budgets, spending limits, prepaid balance limits, and your payment threshold differ*)

**Short rules:** budget = what we want to spend; spending limit = hard ceiling; payment threshold = when Meta charges the card (not a budget); Meta sets some daily/prepaid limits. Week 1 stay ≤ **$25/wk** (~**$3.50/day**).

## Terms of Service (agents)

- Official: https://www.facebook.com/legal/terms  
- Agent summary: **`notes/meta-terms-of-service.md`**  
- Business ads/Page also imply **Commercial Terms**, **Ad Standards**, **Self-Serve Ad Terms**, **Pages policy** (links in that note).  
- Do not misappropriate tokens, run deceptive ads, scrape without permission, or create fake personal accounts for the brand.

## Advertising Standards (agents)

- Official: https://transparency.meta.com/policies/ad-standards/  
- Agent summary: **`notes/meta-ad-standards.md`**  
- Ads reviewed (often within 24h); can be re-reviewed after live. Landing page must match ad. No weapons/tobacco/illicit drugs/counterfeits/deceptive claims. No Meta ad-data transfer to brokers. Week 1 = outdoor utility hero only, truthful creatives.

## Lead Ad Terms (agents)

- Official: https://www.facebook.com/legal/leadgen/tos  
- Agent summary: **`notes/meta-lead-ad-terms.md`**  
- **Default Week 1: do not run Lead Ads** — use traffic/sales to Shopify PDP. If lead gen is used: no minors; never sell leads; purpose-limited use; disclosures + security; no sensitive fields (Ad Standards).

## Security

PHONE pasted the raw token into `STATUS.md` **Next**. Scrubbed on AI-CODING after local store. **Rotate** if the repo is shared or public history retains the string.
