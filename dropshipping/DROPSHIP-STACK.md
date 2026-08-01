# Practical dropshipping stack — Basecamp & Backwoods

**Shop:** `basecampandbackwoods.myshopify.com`  
**Last updated:** 2026-07-27  
**Status:** Phase A live (CJ + Shopify automation). Phases B–D scaffolded below.

This stack is built around what you already run:

- Daily catalog job at **02:00** (`Invoke-DailyCatalogRefresh.ps1`)
- CJ import with **tracked inventory only**
- Clearance lifecycle (discount → 14-day delete)
- **≤ 100 products** hard cap
- No automated purchases

---

## 1. Target stack (recommended)

```
                    ┌─────────────────────┐
                    │   Shopify (Horizon) │
                    │  Online Store live  │
                    │  ≤100 SKUs + tags   │
                    └──────────▲──────────┘
                               │
              Admin API + tags (bb-*, cj-*, spocket-*, etc.)
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
 ┌──────────────┐     ┌────────────────┐     ┌────────────────┐
 │  PRIMARY     │     │  SECONDARY     │     │  MERCH / POD   │
 │  CJdropship  │     │  Spocket       │     │  Printful      │
 │  cost + depth│     │  US/EU speed   │     │  logo apparel  │
 └──────▲───────┘     └───────▲────────┘     └───────▲────────┘
        │                     │                      │
        │              Shopify app                   │
        │                     │                      │
 ┌──────┴─────────────────────┴──────────────────────┴──────┐
 │  OPTIONAL OPS LAYER (pick one when volume hurts)          │
 │  DSers  (AliExpress orders)  OR  AutoDS / Zendrop later   │
 └───────────────────────────────────────────────────────────┘
```

| Layer | Tool | Role | When |
|-------|------|------|------|
| **Store** | Shopify | Storefront, checkout, inventory tags, clearance | Live |
| **Primary supplier** | **CJdropshipping** | Bulk outdoor SKUs, low cost, daily import script | Live |
| **Secondary (fast ship)** | **Zendrop** (preferred) | US-focused heroes + trust; 8–12 SKUs | Next |
| **Secondary alt** | Spocket | **BLOCKED** — human reported payments/billing issues | Skip for now |
| **Secondary alt** | CJ US/EU warehouse tags | Same app as primary; tag `bb-ship:fast` | No new app |
| **Order automation (optional)** | **DSers** *or* keep CJ app | Auto-push paid orders to AliExpress/CJ | When order volume > ~5/day |
| **Brand merch** | **Printful** | Logo tees/hats/stickers (no inventory risk) | After brand solid |
| **Not in stack yet** | AutoDS | Heavy automation; avoid 3 apps at once | Phase D |

**Why this combo**

| Need | Who covers it |
|------|----------------|
| Cheap volume catalog | CJ |
| Faster US shipping story | **Zendrop** (or CJ local warehouses) |
| Your rules (cap 100, clearance, tracked stock) | Your PowerShell jobs |
| Branded merch without stock | Printful |
| Avoid tool sprawl | One primary + one secondary + optional ops app |

---

## 2. Product routing rules (how to choose supplier)

Every catalog slot gets a **preferred supplier**. Tags on the Shopify product:

| Tag | Meaning |
|-----|---------|
| `bb-supplier:cj` | Fulfilled / sourced via CJ |
| `bb-supplier:spocket` | Fulfilled via Spocket |
| `bb-supplier:printful` | POD merch |
| `bb-ship:standard` | Normal 7–20 day expectation |
| `bb-ship:fast` | Market as faster (Spocket US/EU) |
| `bb-catalog` / `bb-clearance` / … | Existing lifecycle tags |

### Routing decision tree

```
Is this logo merch / custom print?
  YES → Printful
  NO ↓

Is shipping speed a top selling point for this SKU
OR product is a “trust hero” (ear pro, higher AOV gear)?
  YES → Prefer Zendrop US stock (Spocket blocked on billing)
       OR tag CJ US/EU warehouse SKU as bb-ship:fast
  NO ↓

Default → CJ (existing import catalog)

If preferred supplier OOS / no match:
  1) Try other supplier once
  2) Else skip create (do not list untracked)
  3) If already live → lifecycle may move to clearance
```

### Category defaults

| Collection | Prefer | Why |
|------------|--------|-----|
| Camping, grilling, overland, tools, survival (most) | **CJ** | Price + breadth |
| Shooting *accessories*, higher-ticket trust items | **Zendrop** (or CJ US stock) | Faster, fewer surprises |
| Water sports seasonal impulse | **CJ** first | Margin |
| Apparel (generic) | **CJ** | Cost |
| Logo apparel | **Printful** | Brand control |
| Clearance / discount | Keep original supplier tag | Fulfill from same source until delete |

---

## 3. Pricing stack (one formula, two lanes)

Keep your existing band unless fast-ship COGS forces a bump.

| Lane | Formula | Notes |
|------|---------|--------|
| **CJ lane** | Retail ≈ cost × **2.5–3.5** (default 3.0) | Current import script |
| **Fast-ship lane** (Zendrop / US warehouse) | Retail ≈ cost × **2.0–2.8** | Higher COGS; less markup room |
| **Clearance** | compare_at = original × **1.10**, price = compare_at × **0.80** | Lifecycle job |
| **Printful** | Printful base + **$8–15** brand margin | Set in Printful product |

Floor: never sell below cost + shipping buffer.

---

## 4. Ops stack (day-to-day)

### Automated (already)

| Time | Job |
|------|-----|
| **02:00 daily** | Import CJ → lifecycle → publish Online Store |
| Continuous | Horizon theme, tags, collections |

### Human (required)

| Task | Frequency |
|------|-----------|
| Connect Zendrop (or CJ US stock) for 8–12 fast heroes | Once + monthly review |
| Sample top 5 heroes (quality) | Once per season |
| Refunds / exceptions | As needed |
| Check `api/logs/daily-catalog-*.log` | Weekly glance |
| Payments, legal, ads | Human only |

### Order flow (target)

```
Customer pays on Shopify
        │
        ├─ SKU tagged bb-supplier:cj
        │     → Fulfill via CJ app / CJ portal (or AutoDS later)
        │
        ├─ SKU tagged bb-supplier:zendrop
        │     → Zendrop app auto-fulfill
        │
        ├─ SKU tagged bb-supplier:spocket  (only if billing fixed)
        │     → Spocket app auto-fulfill
        │
        └─ SKU tagged bb-supplier:printful
              → Printful auto-fulfill
```

### Fast-ship tagging (after human imports 8–12)

```powershell
# Preferred (Zendrop)
powershell -File .\api\Invoke-TagFastShipProducts.ps1 -Supplier zendrop -CreatedSinceHours 48

# No new app — protect CJ US/EU heroes
powershell -File .\api\Invoke-TagFastShipProducts.ps1 -Supplier cj-local -TitleContains "Your Product"

# Spocket only if payments work again
powershell -File .\api\Invoke-TagFastShipProducts.ps1 -Supplier spocket -CreatedSinceHours 48
```


**Rule:** Never list a product without knowing which lane fulfills it.

---

## 5. Rollout phases

### Phase A — Live now

- [x] Shopify store + Horizon theme  
- [x] CJ credentials + import script  
- [x] Collections (camping → tools)  
- [x] Daily job + 100 cap + clearance  
- [x] Supplier registry scaffold (`api/stack/`)  

### Phase B — Spocket secondary (next)

1. Create Spocket account (human).  
2. Install **Spocket** Shopify app on `basecampandbackwoods`.  
3. Connect store; **do not** bulk-import 200 SKUs.  
4. Hand-pick **8–12** US/EU products that fill gaps or upgrade trust heroes.  
5. Tag them `bb-supplier:spocket` + `bb-ship:fast`.  
6. Keep total store **≤ 100** (Spocket counts toward cap).  
7. Add shipping copy: “Some items ship from US/EU warehouses — see product page.”  

**Success:** 8–12 Spocket SKUs live, no automation conflict with CJ daily import (import should **not** overwrite Spocket products).

### Phase C — Order automation

When manual CJ order entry is painful:

1. Install **CJ official Shopify app** *or* **DSers** (if you add AliExpress sources).  
2. Map only `bb-supplier:cj` products.  
3. Leave Spocket/Printful on their own apps.  
4. Test with **one real low-cost order** you place and refund/accept as sample cost (human).  

### Phase D — Brand merch (Printful)

1. Install Printful.  
2. 3–5 SKUs: tee, cap, sticker, hoodie (optional).  
3. Use transparent logo file already in `api/theme-assets/`.  
4. Tag `bb-supplier:printful`.  
5. Exclude Printful titles from CJ import catalog list.

### Phase E — Only if needed

- **Zendrop** or **AutoDS** as unified ops (replace DSers, not add on top of everything).  
- Second daily job for Spocket stock sync (if Spocket app doesn’t cover it).  

---

## 6. Protect existing automation

| Risk | Mitigation |
|------|------------|
| CJ daily import overwrites Spocket product | Import matches by **title** in `$Catalog` only; Spocket products use titles **not** in CJ catalog, or tag `bb-supplier:spocket` and skip in import |
| Over 100 products | Import `-MaxProducts 100` + lifecycle cap |
| Double fulfillment | One `bb-supplier:*` tag per product; never two |
| Untracked inventory | Spocket still needs tracked Shopify inventory or app-managed stock; keep policy deny + levels |
| Clearance on Spocket SKU | Lifecycle applies to all; OK — still discount then remove |

**Import skip rule (to implement when Spocket goes live):**

```text
If product has tag bb-supplier:spocket OR bb-supplier:printful
  → CJ import must not update/delete it
```

See `api/stack/suppliers.json` and future filter in `Invoke-CjToShopifyImport.ps1`.

---

## 7. Credentials layout (secrets never in git)

| Supplier | Path on this PC |
|----------|-----------------|
| Shopify | `%USERPROFILE%\.shopify-link\` |
| CJ | `%USERPROFILE%\.cj-link\` |
| Spocket | `%USERPROFILE%\.spocket-link\` (create when ready: `api-key`, `notes.txt`) |
| Printful | `%USERPROFILE%\.printful-link\` (create when ready) |

---

## 8. Config files in this repo

| File | Purpose |
|------|---------|
| `api/stack/suppliers.json` | Supplier registry + roles + priorities |
| `api/stack/routing-rules.json` | Category → preferred supplier |
| `api/stack/README.md` | How to edit routing without breaking daily job |

---

## 9. This week’s checklist (practical)

**You (human)**

1. [ ] Open Spocket → create account → install Shopify app  
2. [ ] Shortlist 8–12 US warehouse products that fit collections  
3. [ ] Confirm they don’t duplicate existing CJ titles  
4. [ ] Note monthly Spocket cost vs expected lift  

**Agent / scripts (when you say go)**

1. [ ] Skip-list in CJ import for `bb-supplier:spocket|printful`  
2. [ ] Tag helper for Spocket products after import  
3. [ ] Shipping policy page blurb for mixed warehouses  
4. [ ] Optional: Printful logo merch pack  

---

## 10. What we are *not* doing

- Auto-buying samples or placing customer orders from agents  
- Installing three competing automation apps at once  
- Flooding the store with Spocket’s full catalog  
- Breaking the 100-product / clearance rules  

---

## 11. Decision log

| Date | Decision |
|------|----------|
| 2026-07-27 | Primary **CJ**, secondary **Spocket**, merch **Printful**, ops app deferred |
| 2026-07-27 | Cap 100 + clearance stays source-of-truth for catalog churn |
