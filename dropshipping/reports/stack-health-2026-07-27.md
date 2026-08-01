# Stack health - 2026-07-27 11:17

| Check | Value |
|-------|-------|
| Shop domain | basecampandbackwoods.myshopify.com |
| Shop display name | Basecamp and Backwoods |
| Payments | Shopify Payments OK (balance readable) |
| Storefront password | off (public) |
| Active products | 66 / 100 max |
| CJ tagged | 56 |
| Zendrop tagged | 10 |
| Spocket tagged | 0 (blocked/billing - skip) |
| Fast-ship (bb-ship:fast) | 10 |
| Printful tagged | 0 |
| Clearance | 0 |
| Removal scheduled | 0 |
| Removal unscheduled | 0 |
| Untagged supplier | 0 |
| Daily task | Ready |
| Next daily run | 07/28/2026 02:00:00 |

## Human blockers

1. Fast-ship present (zendrop=10, bb-ship:fast=10) - review shipping copy on those PDPs.
2. **Printful** - optional later for logo merch.

## Autonomous (OK without human)

- CJ daily import + lifecycle + Online Store publish + health snapshot
- Theme, logo, collections, catalog cap 100
- Stack docs: api/DROPSHIP-STACK.md
- Pages: About / Contact / FAQ / Shipping / Refund (branded)

## STATUS sync

Human todos live in repo root `STATUS.md`. After Zendrop/CJ-local import, agents run Invoke-TagFastShipProducts.ps1 + this health check. Spocket is blocked.

