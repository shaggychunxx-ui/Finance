# Store status snapshot — Basecamp & Backwoods

**As of:** 2026-08-01 (consolidated into Finance)  
**Source:** ShopifyDS STATUS + grok-shared-workspace Done log + import reports

## Live store

| Field | Value |
|-------|--------|
| Shop | `basecampandbackwoods.myshopify.com` |
| Theme | Horizon outdoor palette / hero / grids (polish applied) |
| Main menu | Home · Products (collections nest) · About · FAQ · Contact |
| Catalog | **18/18** (and expanded CJ imports) **active** with CJ images (4–6 ea) + `cj-pid` tags |
| Pricing | Research target retail; **2.5–3.5×** CJ cost (default ~3×) |
| Inventory rule | Tracked stock only (`inventory_management = shopify`) |
| Purchases by agents | **None** (policy) |

## Marketing

| Field | Value |
|-------|--------|
| Weekly budget plan | **$25** (~$3.50–$4/day) Meta-first |
| Paid ads live? | **No** |
| Spend to date | **$0** |
| Week 1 hero | Portable Water Filter Straw · **$29.99** · Zendrop fast-ship only |
| Hero PDP | [mini-portable-filter-with-water-purifier-straw](https://basecampandbackwoods.myshopify.com/products/mini-portable-filter-with-water-purifier-straw) |
| CJ twin | Retitled **Standard Ship** — do **not** advertise |
| maxCAC (hero) | ~**$12.30** (tight; see margins audit) |
| Meta first payment | **WAITING** — human ~$2 so card charges, then finish connect |
| Creatives | Briefs ready; **assets not shot** |
| FB Page | Required for proper Ads API launch |

## Supplier stack

| Layer | Tool | Status |
|-------|------|--------|
| Store | Shopify | Live |
| Primary | CJdropshipping | Live (API import + tags) |
| Secondary fast-ship | Zendrop | Preferred for hero ads |
| Spocket | — | **Blocked** (billing issues) |
| Printful | POD merch | Later |

## Automation (ShopifyDS)

| Piece | State |
|-------|--------|
| **API / process host** | **GROMIT** (cutover 2026-08-06; was AI-CODING) |
| ShopifyDS agent automation | **PAUSED** (human 2026-07-30) |
| Daily catalog job | Installed on GROMIT; Disabled while paused / until secrets imported |
| Secrets | Pending offline copy AI-CODING → GROMIT (`Migrate-ApiSecrets.ps1`) |
| Unattended bus for ShopifyDS | No auto claim until human unpauses |

Resume steps: see ShopifyDS `STATUS.md` § How to resume automation.

## Human still needed

1. Theme + payments polish (if not finished in admin)  
2. Meta first-payment (~$2) + durable Marketing token / system user  
3. Shoot Week 1 creatives (see marketing-plan §14)  
4. Optional: CJ Shopify app for **order fulfillment** only (catalog already via API)  
5. Prefer rotate any CJ/Meta secrets that ever hit STATUS history  

## Where to dig deeper

- Plans & research → parent folder `dropshipping/`  
- Ops scripts → ShopifyDS `api/`  
- Team dual-PC bus → grok-shared-workspace  
