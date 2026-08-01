# Meta Pixel on storefront — verification (2026-07-28)

**Request (PHONE):** finish setting up Meta pixel on Shopify webpage base code.  
**Machine:** AI-CODING · **Shop:** basecampandbackwoods.myshopify.com

## Result: already live (no theme edit needed)

Shopify injects the Meta (Facebook) pixel through the **Facebook & Instagram** sales channel + **web pixels manager**, not via a hand-pasted `fbq` snippet in `layout/theme.liquid`.

| Check | Status |
|-------|--------|
| Sales channel **Facebook & Instagram** installed | Yes (`facebook-ads`) |
| Storefront `webPixelsConfigList` includes Facebook pixel | Yes |
| Pixel ID | **`1911518699818229`** (public in page HTML) |
| `pixel_type` | `facebook_pixel` |
| Runtime | `OPEN` |
| Data sharing | `optimized` · `share_all_events` |
| Privacy purposes | ANALYTICS, MARKETING, SALE_OF_DATA |
| Theme `{{ content_for_header }}` present (injection point) | Yes (Horizon MAIN) |
| Manual `fbq` / `fbevents.js` in theme.liquid | **None** (correct — avoid double-fire) |
| Hero PDP published to Facebook publication | Yes |
| Sample of 25 active products on FB publication | 25/25 |

Homepage + hero PDP HTML both contain the pixel config (verified via public fetch).

## What agents did **not** do

- Did **not** paste a classic Meta “base code” block into `theme.liquid` (would **duplicate** the channel pixel and break attribution).
- Did **not** place ads or spend.
- Cannot open Meta **Events Manager** from this host to click “Test events” or confirm server-side CAPI green checks — human-only.

## Human verify (2 minutes)

1. Meta Events Manager → pixel **`1911518699818229`** → **Test events**.  
2. Open storefront (incognito): homepage + [hero PDP](https://basecampandbackwoods.myshopify.com/products/mini-portable-filter-with-water-purifier-straw).  
3. Confirm **PageView** (and **ViewContent** on PDP). Optional: ATC once → **AddToCart**.  
4. Ads Manager / Shopify **Facebook & Instagram** channel: leave channel connected; do not also add a second “manual pixel” app.

## Local note

Pixel ID is storefront-public (not a secret). Optional local file: `~\.meta-link\pixel-id` (agents may write it; never put Marketing API tokens in git).

## Implication for ads

Pixel base tracking is **ready**. Remaining blockers for Week 1 paid ads are still: **creatives** + human Ads Manager launch (or optional `~\.meta-link\marketing-api-token`). See `marketing-plan.md` §14–§17.
