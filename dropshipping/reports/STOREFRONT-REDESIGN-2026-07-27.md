# Storefront redesign — 2026-07-27

## Goal
Less generic “Shopify default” feel: outdoor lifestyle photography, clearer merchandising, tailored palette.

## What shipped

### Theme
- Stayed on **Horizon** (main). Remote ZIP install of Dawn/Craft returned **422** from Admin API (blocked on this shop).
- Touched `layout/theme.liquid` for cache invalidation; rebuilt `templates/index.json`.

### Hero collage (real photography, Unsplash License)
Composed collage (`api/theme-assets/hero-collage.jpg`) from:

| File | Subject | Photographer |
|------|---------|--------------|
| camp-tent | Camping tent night | Toomas Tartes |
| hike-trail | Hiking trail | Holly Mandarich |
| campfire | Campfire social | Mike Erskine |
| bbq-grill | Outdoor grilling | Chad Montano |
| road-trip | Overland road trip | Dino Reichmuth |
| lake-camp | Lakeside camp | Toomas Tartes |

Credits: `api/theme-assets/IMAGE-CREDITS.txt`  
Not AI-generated; free commercial use under [Unsplash License](https://unsplash.com/license); no watermarks.

Uploaded to Shopify Files as `shopify://shop_images/hero-collage.jpg` (+ collection covers).

### Homepage structure
1. **Hero** — collage + “Out there looks good on you.” + dual CTAs  
2. **Trust marquee** — shipping / checkout / returns  
3. **Shop by adventure** — Camping · Grilling · Overland (collection list + cover images)  
4. **Trail favorites** — curated best-sellers (6 mixed heroes)  
5. **Camp nights** — camping collection  
6. **Fire and flavor** — grilling  
7. **Miles from nowhere** — overland  

### Product organization
- **Best Sellers** re-curated: lantern, hammock, grill, thermometer, tire compressor, LED light  
- **Frontpage** collection filled with 8 cross-category picks  
- Collection cover images set for camping, grilling, overland, best-sellers, new arrivals  

### Palette
- Parchment `#F3EFE6`, charcoal green `#1A2214`, forest `#2C4A32`, copper CTA `#B5521E`  
- Softer radius, portrait product cards, lift hover  

## Scripts
- `api/theme-assets/build_collage.py` — collage builder  
- `api/Invoke-StorefrontRedesign.ps1` — upload + full redesign  
- `api/Apply-RedesignFinish.ps1` — apply homepage JSON + collection images  

## Verify
Live theme sections (confirmed via `/?sections=` API):
- Hero collage + new copy  
- Shop by adventure  
- Trail favorites / Camp nights  

Public HTML edge cache may lag for bots; hard-refresh or:

`https://basecampandbackwoods.myshopify.com/?preview_theme_id=156591489187`

## Human follow-ups
- Rename shop from **My Store** → **Basecamp & Backwoods** (Settings → Store details)  
- Optional: install Dawn/Craft manually from Theme Store if a full theme swap is preferred  
- Optional: custom logo wordmark  
