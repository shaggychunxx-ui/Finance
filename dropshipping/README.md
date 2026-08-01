# Dropshipping — Basecamp & Backwoods (canonical info)

**Canonical home for dropshipping business info** lives in this Finance folder (PHONE request 2026-08-01).  
Operational automation / Shopify agent code stays in the private **ShopifyDS** repo; this tree is the single place to read plans, research, margins, stack, and reports without hunting multiple repos.

| | |
|--|--|
| **Store** | Basecamp and Backwoods |
| **Shop domain** | `basecampandbackwoods.myshopify.com` |
| **Niche** | Outdoor / camping / trail / grill / overland (+ expanded shortlist) |
| **Catalog** | ~18+ active products with CJ images; tracked inventory only |
| **Ops code repo** | https://github.com/shaggychunxx-ui/ShopifyDS |
| **Team bus** | `grok-shared-workspace` (`work/dropshipping-store/` is a legacy mirror) |
| **Secrets** | Never in git — `%USERPROFILE%\.shopify-link\`, `~\.cj-link\`, `~\.meta-link\` |

---

## Start here

| Doc | What it is |
|-----|------------|
| **[STORE-STATUS.md](STORE-STATUS.md)** | Live snapshot: catalog, ads, blockers, human TODOs |
| **[MISSION.md](MISSION.md)** | North star (CX, revenue, quality, multi-store) |
| **[product-research.md](product-research.md)** | Niche map, Tier-1/2 shortlist, 2.5–3.5× markup rule |
| **[marketing-plan.md](marketing-plan.md)** | $25/wk Meta-first plan, hero SKU, creatives, maxCAC |
| **[shopify-setup-plan.md](shopify-setup-plan.md)** | Brand, theme, nav, pages, launch checklist |
| **[DROPSHIP-STACK.md](DROPSHIP-STACK.md)** | CJ primary + Zendrop secondary stack, tags, jobs |

## Money / margins

| Doc | What it is |
|-----|------------|
| **[margins/zendrop-margin-audit-2026-07-28.md](margins/zendrop-margin-audit-2026-07-28.md)** | Week 1 hero unit economics (maxCAC ~$12.30) |
| Marketing plan §15 | Full hero margin math (in `marketing-plan.md`) |

## Reports (imports / storefront)

Under **[reports/](reports/)**:

- CJ import results (2026-07-27, 2026-07-28)
- Products menu + apply result
- Storefront polish / redesign
- Import run analysis, stack health

## Notes (Meta, demos, pipeline)

Under **[notes/](notes/)**: Meta ToS/ad standards summaries, Marketing API setup notes, pixel verify, census/Pew demographics, agent pipeline / platform agents.  
**[notes/CJ-CREDENTIALS.md](notes/CJ-CREDENTIALS.md)** — *where* secrets live (no secret values).

---

## Where code still lives (not moved)

| Location | Role |
|----------|------|
| **ShopifyDS** `api/*.ps1` | CJ→Shopify import, daily catalog, storefront polish, publish |
| **ShopifyDS** `src/` | Collectors / analysts / decision agents |
| **ShopifyDS** `STATUS.md` | Ops bus (automation currently **PAUSED** 2026-07-30) |
| **grok-shared-workspace** `work/dropshipping-store/` | Early mirror of research + scripts |

Agents doing **ops work** still open ShopifyDS (or a bus task that points there).  
Agents / humans wanting **business info** read **this** folder first.

### Profit → marketing (policy)

When the store has real profit (orders after COGS/fees), reinvest a share into the marketing budget. Until then: starter **$25/week**. Full rules in `MISSION.md`.

### Safety

- No automated purchases  
- No secrets in git  
- Human-only: payments, bank, theme final polish, Meta first-payment bootstrap, creatives

---

**Synced from ShopifyDS + gsw mirror:** 2026-08-01 (AI-CODING).  
When plans/margins change, update **here** first, then mirror back to ShopifyDS if ops still need a local copy.
