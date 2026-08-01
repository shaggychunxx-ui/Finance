# Import run analysis — 2026-07-27

**Runs:** full CJ→Shopify import (tracked-inventory rule) ×2  
**Result:** `18/18` updated · `0` skipped · `0` errors · ~4.7 min/run  
**Shop:** `basecampandbackwoods.myshopify.com`

## What worked

| Area | Observation |
|------|-------------|
| Tracked-inventory rule | All CJ matches had known warehouse qty; no `skip-no-inventory` |
| Shopify tracking | `inventory_management = shopify`, `inventory_policy = deny` on all variants |
| Inventory levels API | **Required.** Product REST `inventory_quantity` left stock at **0** on first run (store sold-out under `deny`). Second run used `inventory_levels/set` → stock correct (capped at 9999) |
| Collections / menu | All 18 re-collected; Products menu already OK |
| Throughput | Stable under CJ rate-limit sleeps; no 429 after backoff path |

## Critical fix applied mid-session

1. **Bug:** Enabling tracking + `deny` without Inventory Levels set → **available = 0** on storefront.  
2. **Fix:** `Set-ShopifyTrackedInventory` after create/update: `inventory_items` tracked + `POST /inventory_levels/set.json` at primary non-legacy location (`Shop location` / `86797713571`).  
3. Cap CJ aggregate warehouse counts at **9999** for storefront sanity.

## Match-quality issues (highest impact improvements)

Score threshold (≥10) is too weak vs brand title intent. Notable mismatches:

| Brand title | CJ match problem | Suggested fix |
|-------------|------------------|---------------|
| Compact Survival Multitool Kit | **Survival shovel** multitool | Require `multitool`/`plier`/`knife`; reject `shovel` |
| Wireless Bluetooth Meat Thermometer | **Scraper spatula + thermometer** hybrid; no Bluetooth | Must: `bluetooth` OR `wireless`; reject `spatula`/`scraper` |
| Off-Road LED Pod Light (12V) | Full **light bar** 8–50″ | Prefer `pod`/`cube`/`work light`; reject `light bar` width ranges |
| Reusable Non-Stick Grill Mats | **Mesh bag** / grill bag | Must: `mat`/`mats`; reject `bag` alone |
| Portable Folding Tabletop Grill | Cost **$2.47** (suspect tiny/toy or wrong SKU) | Min cost floor for grill (~$8+); prefer weight/size signals |
| Solar Power Bank with Flashlight | Solar panel bank — **flashlight** not verified | Prefer names with `flashlight`/`torch` |

## Pricing / margin notes

- Markup floor **2.5×** correctly raised: hammock **$44.70**, multitool **$46.72**, tire inflator **$45.72** (above research targets when cost is high).  
- Dry bag cost **$1.18** → retail **$22.99** (~19×) — research target kept; fine for ads/margin but look “premium vs cost” risk if reviews mention cheap feel.  
- Grill cost **$2.47** → retail **$49.99** is a **red-flag match** (likely wrong product quality tier).

## Inventory semantics

- CJ `warehouseInventoryNum` is often **network-wide aggregate**, not a reserved SKU count.  
- Cap 9999 is OK for “in stock”; better long-term: sync periodically (cron) or set policy `continue` with tracking for reporting only.  
- Tool roll at **74** is the only low real qty — good deny candidate when depleted.

## Performance improvements

| Opportunity | Why | Effort |
|-------------|-----|--------|
| Skip image wipe/re-add when CJ image set unchanged | Dominant write cost + flaky CDN | Medium |
| Cache CJ matches by brand title + pid (TTL 24h) | Re-run is ~5 min pure re-search | Low |
| Parallelize only non-CJ Shopify inventory sets | After match list is fixed | Low |
| Reduce sleep when no 429 | Faster dry re-imports | Low |
| WhatIf inventory path unit-test | Catch qty=0 regression | Low |

## Product / catalog improvements

1. **Stricter Must/Reject tokens** for the 5 weak heroes above.  
2. **Min score raise** to ~40 for activate, or require Prefer-token hit count ≥2.  
3. **Min cost bands** per category (grill/chair/hammock) to avoid $2 “grill” listings.  
4. **Human review flag** when score &lt; 40 or cost outside band (tag `needs-review`, status draft).  
5. **Periodic inventory refresh** script (no full re-import) from CJ pid tags.  
6. Shop display name still **“My Store”** — human branding in admin.

## Recommended next actions (priority)

1. ✅ Done: inventory_levels set + re-import (stock sellable).  
2. Tighten Must/Reject for multitool, thermometer, LED pod, grill mats, grill.  
3. Add match confidence gate → draft vs active.  
4. Image-diff skip on update.  
5. Optional nightly inventory sync only.
