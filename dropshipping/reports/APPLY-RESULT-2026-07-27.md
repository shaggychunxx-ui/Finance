# Shopify Admin API apply — 2026-07-27

## Auth path that worked

Human provided **Client ID** (32-char hex), **Client secret** (`shpss_…`), and an `atkn_…` string.

Direct use as `X-Shopify-Access-Token` (with/without `shpat_` prefix, Basic auth, GraphQL, Storefront) → **401**.

**Working path:** OAuth **client credentials** grant:

```http
POST https://{shop}/admin/oauth/access_token
{ "client_id": "...", "client_secret": "...", "grant_type": "client_credentials" }
```

Returns short-lived `access_token` (`shpat_…`, ~24h) + broad Admin scopes. Token stored off-git:

| File | Purpose |
|------|---------|
| `%USERPROFILE%\.shopify-link\shop.domain` | `basecampandbackwoods.myshopify.com` |
| `%USERPROFILE%\.shopify-link\client-id` | Custom app client id |
| `%USERPROFILE%\.shopify-link\client-secret` | Custom app secret |
| `%USERPROFILE%\.shopify-link\admin-api.token` | Current access token |
| `%USERPROFILE%\.shopify-link\token-meta.json` | scope / expires metadata |

`atkn_…` did not authenticate Admin REST/GraphQL or Storefront in this session (saved off-git as `atkn.token` only).

## Shop probe

- **name:** My Store  
- **domain:** basecampandbackwoods.myshopify.com  
- **plan:** basic  
- **currency:** USD  
- **email:** shaggychunxx@gmail.com (from API; not re-committed elsewhere)

## Apply result (`Invoke-ShopifyStoreSetup.ps1`)

| Step | Result |
|------|--------|
| Probe `/shop.json` | OK |
| Custom collections | **6/6** created |
| Pages | **4/5** (Contact → 422 Unprocessable Entity — likely already exists) |
| Draft products | **18/18** created |
| Purchases | **none** |

### Collection IDs

- Camping & Outdoor Gear `336512319651`
- Grilling & Outdoor Cooking `336512352419`
- Overland & Off-Road Accessories `336512385187`
- Bundles & Kits `336512417955`
- Best Sellers `336512450723`
- New Arrivals `336512483491`

### Pages created

- About `123245265059`
- FAQ & Shipping `123245297827`
- Shipping Policy `123245330595`
- Refund Policy `123245363363`
- Contact: **failed 422** (check admin; may pre-exist)

Draft product IDs: `9208444190883` … `9208444780707` (18 shells from `payloads/products-draft.json`).

## Script upgrades this session

- Auto OAuth refresh via `client-id` + `client-secret` (`-RefreshToken` or on probe failure).
- README documents client credentials path.

## Human next (store)

1. Theme / homepage hero from `shopify-setup-plan.md`.
2. Payments + legal: human only in admin.
3. Real supplier products/images/fulfillment — human only (**CJdropshipping ignored** for agent automation per human Next).
4. Optional: rename shop display name from “My Store”.
5. **Never paste tokens into STATUS/tasks** — use `~\.shopify-link\` only.
