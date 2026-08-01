# U.S. Census Bureau data — agent knowledge

**Official hub (always start here):**  
https://www.census.gov/data.html  

**Documented for ShopifyDS agents:** 2026-07-29  
**Store context:** Basecamp and Backwoods · Meta ads **US only** at micro-budget · audiences in `marketing-plan.md` §1 / §7 · Meta targeting still must follow **Ad Standards** (no discriminatory misuse of demographics).

This note tells agents **where to get public US stats** for market sizing, geo interest, income/age context, and planning. It is **not** a substitute for Meta ad policy, privacy law, or primary store analytics.

---

## What the hub is

U.S. Census Bureau **Data and Maps** portal: demographic, economic, and population statistics, visualizations, tools, APIs, and training. Tagline: *Learn about America's people and economy.*

Primary exploration UI: **[data.census.gov](https://data.census.gov)** (linked from the hub).

---

## Tools agents should know

| Tool | URL | Use for Basecamp |
|------|-----|------------------|
| **data.census.gov** | https://data.census.gov | Tables, maps, charts; main query UI |
| **QuickFacts** | https://www.census.gov/quickfacts | Fast state/county/city snapshot (pop, income, housing) |
| **Data Profiles by geography** | https://data.census.gov/profile | Place/county/metro profiles |
| **Population Clock** | https://www.census.gov/popclock | National population context only |
| **Census Business Builder (CBB)** | https://www.census.gov/data/data-tools/cbb.html | Small-business market potential / consumer & business data by area |
| **OnTheMap** | https://onthemap.ces.census.gov | Workforce / commuting patterns (advanced) |
| **Census API** | https://www.census.gov/data/developers.html | Programmatic pulls (need free API key for many endpoints) |
| **API key request** | https://api.census.gov/data/key_signup.html | Local only — never commit keys |
| **NAICS codes** | https://www.census.gov/naics | Industry classification (e.g. outdoor retail context) |
| **America Counts** | https://www.census.gov/library/stories.html | Narrative explainers behind the numbers |
| **Data release schedule** | https://www.census.gov/about/event-calendar.html | When series update |

Developer guides:

- https://www.census.gov/data/developers.html  
- API user guide: https://www.census.gov/data/developers/guidance/api-user-guide.html  
- Available APIs: https://www.census.gov/data/developers/data-sets.html  

How-to for data.census.gov: https://www.census.gov/data/what-is-data-census-gov.html  

---

## High-value survey programs (names to search)

| Program | Why it matters |
|---------|----------------|
| **American Community Survey (ACS)** | Age, income, education, housing, commuting — best ongoing demographic detail |
| **Decennial Census** | Full count; less frequent; baseline pop/housing |
| **Population Estimates / Projections** | Between-census population change |
| **County Business Patterns (CBP)** | Establishments/employment by industry & county |
| **Economic Census** | Business structure (less frequent) |
| **SAIPE** | Small-area income & poverty |
| **Metropolitan/Micropolitan** | Metro definitions for geo targeting research |

ACS guidance: https://www.census.gov/programs-surveys/acs/guidance.html  

---

## How agents should use Census data here

### Good uses

1. **Market sizing** — rough counts of adults in age bands in a state/metro (ACS).  
2. **Geo prioritization** — which states/metros have density + income that might support outdoor gear (not “exclude protected classes”).  
3. **Creative/context** — “weekend car camping” audiences exist where vehicle ownership / housing type patterns differ (use carefully; don’t overclaim).  
4. **Multi-store planning** — when adding niches/sites (`MISSION.md`), size US niches with public stats before ad spend.  
5. **Reports for human** — cite series + year + geography (e.g. “ACS 5-year, Travis County, median household income”).

### Bad / forbidden uses

1. **Do not** use Census fields to build Meta targeting that **wrongfully discriminates** or implies personal attributes in ad copy (see `notes/meta-ad-standards.md`).  
2. **Do not** invent “Census says outdoor shoppers are…” without a real table/source.  
3. **Do not** treat Census as Meta interest targeting — Meta interests ≠ Census variables.  
4. **Do not** put Census API keys in git or STATUS.  
5. **Do not** replace Shopify/Meta conversion data with Census for ROAS decisions — Census is **macro**, store pixel is **micro**.

### Week 1 ad reality

Marketing plan already sets: **US only**, ages roughly **25–54**, outdoor interests, **$25/wk**. Census can **inform** “where demand might be” later; it does **not** unblock ads (still need creatives + FB Page + durable token).

---

## Suggested workflow for an agent research pass

1. Open https://www.census.gov/data.html → **data.census.gov** or **QuickFacts**.  
2. Pick geography: United States → state → metro/county as needed.  
3. Prefer **ACS 5-year** estimates for small areas (more stable).  
4. Pull a few variables only: population, age distribution, median household income, % owner-occupied if relevant.  
5. Write a short note under `notes/` or task Result with **links + vintage** (survey year).  
6. Recommend Meta tests in plain language (e.g. “test lookalikes after sales; optional state bias toward X only if shipping/unit economics support”) — human approves geo splits.  

**Census Business Builder** is especially useful when a human asks “where should we expand” without needing raw API work.

---

## Privacy & citation

- Census publishes **aggregated** statistics with disclosure avoidance — still cite properly: https://www.census.gov/about/policies/citation.html  
- Privacy/quality policies: https://www.census.gov/about/policies/privacy.html · https://www.census.gov/about/policies/quality.html  
- Never re-identify individuals (not possible from proper aggregates; don’t try).

---

## ShopifyDS agent checklist

1. Hub: https://www.census.gov/data.html  
2. Default explore: https://data.census.gov + QuickFacts for fast answers  
3. Business market tools: Census Business Builder when sizing local/regional demand  
4. Cite series + year + geo in any STATUS/task output  
5. Align recommendations with `marketing-plan.md` (US-first, micro-budget)  
6. Align targeting ideas with `notes/meta-ad-standards.md` (no discriminatory exclusion hacks)  
7. API key only under local config (e.g. `~\.census-link\` if added later) — never git  
8. Prefer store + Meta performance data once ads run; Census for planning only  

---

## Related team docs

| Doc | Role |
|-----|------|
| `notes/pew-demographic-data-sources.md` | Pew’s guide to ACS/CPS/SIPP/IPUMS & other demographic sources |
| `notes/demographic-tracking-agent.md` | In-repo DemographicTrackingAgent framework |
| `marketing-plan.md` | Audiences, US-only Week 1 |
| `MISSION.md` | Multi-niche / multi-store growth |
| `notes/meta-ad-standards.md` | Legal limits on demographic targeting in ads |
| `product-research.md` | Catalog niches |
