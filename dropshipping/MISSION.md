# Mission — ShopifyDS

## North star

Build **excellent customer experience and service**, generate **as much revenue as possible**, and sell **quality products** across **multiple niches** — with a path to **more Shopify websites** over time.

| Pillar | Meaning |
|--------|---------|
| **Excellent CX & service** | Clear storefront, honest shipping/expectations, easy support path, reliable fulfillment (tracked stock, no phantom inventory) |
| **Maximize revenue** | Conversion + traffic + margin-aware catalog + ads that pay for themselves |
| **Quality products** | Prefer known stock, real suppliers, lock tags so we don’t overwrite good listings |
| **Multiple niches / more Shopify sites** | This repo is the **ops bus + playbook**, not “only one brand forever” |

This is a multi-brand dropship/ops system with **customer trust first**, then scale.

---

## Operating principles (agents + humans)

1. **CX before catalog spam** — tracked inventory only; clear shipping tiers (e.g. fast Zendrop vs standard CJ); don’t advertise the wrong twin SKU.
2. **Revenue with unit economics** — protect margin when choosing ads and products (see store marketing plans for maxCAC).
3. **Quality over “more SKUs”** — catalog caps and clearance exist; don’t flood with junk.
4. **Niches as brands** — one strong store per niche first; next site = new niche + new Shopify, reuse tooling.
5. **Service** — fulfillment and order issues stay human-confirmed where required; no silent auto-purchase chaos.
6. **No secrets in git** — credentials only under local link folders (`~\.shopify-link\`, etc.).

---

## Profit → marketing budget (policy)

**When there is profit, add it to the marketing budget.**

| Rule | Detail |
|------|--------|
| **Trigger** | Real profit from the store (orders after COGS / fees — not vanity traffic) |
| **Action** | Increase the weekly marketing / ad budget with a share of that profit |
| **Not a task** | Do **not** run one-off “reinvest earnings” research tasks when revenue is $0 |
| **Until profit exists** | Keep the planned starter budget (e.g. Basecamp **$25/wk** in `marketing-plan.md`); focus on launch, creatives, and conversion |
| **Agents** | Do not invent reinvest reports or change ad spend unless **profit is confirmed** and a human or explicit task authorizes the budget change |

Cancelled predecessor task: `tasks/done/2026-07-28-boxone-reinvest-earnings-marketing.md` (was a premature snapshot when intent was this ongoing policy).

---

## Current footprint

| | |
|--|--|
| **Store 1** | **Basecamp and Backwoods** — outdoor / camping / trail niche · `basecampandbackwoods.myshopify.com` |
| **Playbook** | `marketing-plan.md`, `product-research.md`, `shopify-setup-plan.md`, `api/` |
| **Future** | Additional Shopify sites = additional niches; same bus (STATUS/tasks), per-store creds and brand rules |

### Multi-store direction (later)

Same patterns should scale: supplier stack, catalog lifecycle, marketing playbook template, STATUS/tasks bus — **per store config** (creds, domain, brand voice, niche product rules), not copy-paste chaos.

---

## Related docs

| Doc | Role |
|-----|------|
| [README.md](README.md) | Repo map |
| [RULES.md](RULES.md) | Multi-PC leadership + domain constraints |
| [STATUS.md](STATUS.md) | Live handoff |
| [marketing-plan.md](marketing-plan.md) | Store 1 ads / budget (Week 1+) |
| [notes/us-census-data.md](notes/us-census-data.md) | US Census hub for market/geo research (https://www.census.gov/data.html) |
| [notes/pew-demographic-data-sources.md](notes/pew-demographic-data-sources.md) | Pew map of demographic datasets (ACS, CPS, SIPP, IPUMS, …) |
