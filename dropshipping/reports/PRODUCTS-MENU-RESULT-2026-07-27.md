# Products + Menu setup - 2026-07-27

## Summary

| Item | Result |
|------|--------|
| Shop | `basecampandbackwoods.myshopify.com` |
| Products | **18/18 active** (were draft) |
| Research prices restored | yes (from `payloads/products-draft.json`) |
| Collections wired | Camping 9 · Grilling 5 · Overland 4 · Best Sellers 6 · New Arrivals 18 |
| Main menu **Products** | **updated** (nested collections) |
| CJ API auto-match | poor quality for outdoor keywords — most links discarded |
| CJ verified links kept | 2 (water filter straw, tool roll) |
| Bad CJ images | removed from 16 products |
| Purchases / orders | **none** |

## Main menu (live)

- Home
- **Products** (catalog)
  - Shop All
  - Best Sellers
  - New Arrivals
  - Camping & Outdoor
  - Grilling & Cooking
  - Overland & Off-Road
  - Bundles & Kits
- About
- FAQ & Shipping
- Contact

Storefront: https://basecampandbackwoods.myshopify.com

## Active products (research prices)

| Title | Price | Collection | CJ |
|-------|-------|------------|-----|
| Solar Rechargeable Camping Lantern - 3 Light Modes | 29.99 | camping-outdoor | await app |
| Double Camping Hammock with Mosquito Net | 39.99 | camping-outdoor | await app |
| Foldable Aluminum Camp Chair with Carry Bag | 34.99 | camping-outdoor | await app |
| Inflatable Camping Sleeping Pad | 32.99 | camping-outdoor | await app |
| Compact Survival Multitool Kit | 24.99 | camping-outdoor | await app |
| Portable Water Filter Straw | 19.99 | camping-outdoor | **verified** `cj-pid:2607270545521612100` |
| Waterproof Dry Bag 20-30L Roll-Top | 22.99 | camping-outdoor | await app |
| Collapsible Folding Camp Table | 36.99 | camping-outdoor | await app |
| Solar Power Bank with Flashlight | 34.99 | camping-outdoor | await app |
| Wireless Bluetooth Meat Thermometer | 29.99 | grilling-cooking | await app |
| Portable Folding Tabletop Grill | 49.99 | grilling-cooking | await app |
| Grilling Tool Set with Carry Case | 27.99 | grilling-cooking | await app |
| Reusable Non-Stick Grill Mats (Set) | 18.99 | grilling-cooking | await app |
| Compact Nesting Camp Cookware Set | 42.99 | grilling-cooking | await app |
| Off-Road LED Pod Light (12V) | 39.99 | overland-offroad | await app |
| Portable Tire Air Compressor | 44.99 | overland-offroad | await app |
| Universal Phone / GPS Mount | 21.99 | overland-offroad | await app |
| Weatherproof Tool Roll Organizer | 26.99 | overland-offroad | **verified** `cj-pid:2081671771875475458` |

## Script

```powershell
powershell -ExecutionPolicy Bypass -File .\work\dropshipping-store\api\Invoke-ShopifyProductsMenuSetup.ps1 -RefreshToken
```

Also: price/cleanup pass was applied after the first run (CJ keyword search returned many false positives — e.g. wheelchair for camp chair — so retail was restored and bad images stripped).

## Human next

1. Install **CJdropshipping Shopify app** on the shop → import real supplier listings with correct images for the 16 `awaiting-cj-app-import` products (or replace shells).
2. Theme homepage polish (Products nav already works in Online Store navigation).
3. Payments + legal — human only.
4. Optional: upload hero photos for products without images.

## Notes

- Secrets stay under `%USERPROFILE%\.shopify-link\` and `%USERPROFILE%\.cj-link\` only.
- CJ REST search is usable for probes; **do not trust loose auto-match** for catalog images/prices.
- Fulfillment still requires the CJ Shopify app (or manual order process) — this work does not place orders.
