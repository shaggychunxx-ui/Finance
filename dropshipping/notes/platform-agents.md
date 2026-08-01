# Platform agents — Shopify + sales / product / marketing

**Code:** `src/platforms/` · `buildAgentSystem().platformRegistry`  

**Scope for this business:** agents for **Shopify** and every **sales, product, or marketing** platform you are (or will be) connected to.  
**Rule:** **One connected account → one `PlatformAgent`** with that platform’s full **rules** + **functions**.

```
Shopify (sales + product + marketing on-store)
Meta     (marketing / paid ads)
CJ       (product supply)
Zendrop  (product supply, fast-ship)
Spocket  (product — blocked)
Printful (product/merch — planned)
```

Not in this scope by default: pure dev tools (GitHub, Vercel), unless you register them later.

---

## Connected accounts (seeded)

| Domain | Platform | Account agent | Status |
|--------|----------|---------------|--------|
| **Sales + product + marketing** | **Shopify** | `basecampandbackwoods.myshopify.com` | **live** |
| **Marketing** | **Meta** | `act_159153097599967` | **live** (ads still blocked on creatives/Page/token) |
| **Product** | **CJ** | `cj-primary` | **live** |
| **Product** | **Zendrop** | `3436558` | **live** |
| **Product** | **Spocket** | `spocket-blocked` | **blocked** (billing) |
| **Product** | **Printful** | `printful-planned` | **planned** |

### Shopify agent (primary store)

Knows Admin GraphQL/REST surfaces for:

- Catalog, variants, inventory, collections, lifecycle cap  
- Online Store publish, theme, pages, navigation  
- Orders, fulfillments (human-gated), customers (PII-safe)  
- Discounts, Shopify Email, pixels/channels, Markets  
- Webhooks, metafields, scopes  

Critical rules include: **tracked inventory only**, **Online Store publish**, **≤100 products**, **supplier lock tags**, **no secrets in git**, **multi-store token isolation**.

---

## Usage

```js
const { buildAgentSystem } = require('./src/index');
const sys = buildAgentSystem();

// All sales/product/marketing agents
sys.salesProductMarketingAgents;
// or
sys.platformRegistry.listSalesProductMarketingAgents({ status: 'live' });

// Shopify specialist
const shop = sys.getPlatformAgent('shopify', 'basecampandbackwoods.myshopify.com');
shop.getRules();
shop.getFunctions();
shop.research({ topic: 'inventory' });
shop.evaluateAction({
  functionId: 'products.create',
  flags: ['untracked-inventory'],
}); // blocked

// Meta marketing specialist
const meta = sys.getPlatformAgent('meta', 'act_159153097599967');
meta.evaluateAction({
  functionId: 'ads.campaigns',
  flags: ['ad-without-page', 'ad-without-creatives'],
}); // blocked until ready

// NEW Shopify store (new niche site) → NEW agent
sys.connectPlatformAccount({
  platformId: 'shopify',
  accountId: 'new-niche.myshopify.com',
  label: 'Niche Store 2',
  credsPath: '%USERPROFILE%\\.shopify-link-niche2\\',
  status: 'planned',
  meta: { niche: 'fishing', domains: ['sales', 'product', 'marketing'] },
});

// NEW marketing account (e.g. second Meta ad account)
sys.connectPlatformAccount({
  platformId: 'meta',
  accountId: 'act_another',
  label: 'Brand 2 ads',
  status: 'planned',
});
```

### Status

| Status | Meaning |
|--------|---------|
| `live` | Connected and operable (subject to rules) |
| `planned` | Knowledge ready; not live yet |
| `blocked` | Connected or known but must not operate |
| `disconnected` | Removed from ops |

**Secrets:** only `credsPath` patterns (`~\.shopify-link\`, `~\.meta-link\`, `~\.cj-link\`, `~\.zendrop-link\`, …). Never put tokens on the agent or in git.

---

## Adding another sales / product / marketing connection

1. If platform catalog exists (`shopify`, `meta`, `cj`, `zendrop`, …) →  
   `connectPlatformAccount({ platformId, accountId, label, credsPath, status: 'live' })`  
2. If **new** platform (e.g. TikTok Ads, Klaviyo) →  
   `registerPlatform({ id, name, domains: ['marketing'], rules, functions }, firstAccount)`  
3. Prefer catalogs under `src/platforms/catalogs/` for permanent platforms.

---

## Files

| Path | Purpose |
|------|---------|
| `src/platforms/catalogs/shopify.js` | Full Shopify sales/product/marketing surface |
| `src/platforms/catalogs/meta.js` | Meta marketing |
| `src/platforms/catalogs/cj.js` / `zendrop.js` / … | Product suppliers |
| `src/platforms/platformAgent.js` | Per-account agent |
| `src/platforms/platformRegistry.js` | Connect + seed + list SPM agents |
| `test/platformAgents.test.js` | Tests |

Related: `notes/agent-pipeline.md` (collect → analyze → decide), Meta policy notes under `notes/meta-*.md`.
