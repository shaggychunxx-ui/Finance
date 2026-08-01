# Pew Research: data sources for demographic research — agent knowledge

**Official page (always authoritative for this guide):**  
https://www.pewresearch.org/data-sources-for-demographic-research/  

**Documented for ShopifyDS agents:** 2026-07-29  
**Store context:** Basecamp and Backwoods · US-first marketing · pairs with Census hub `notes/us-census-data.md` and Meta policy notes.

This is Pew’s overview of **public data sources their demographers use**. Agents use it as a **map of trusted datasets** and when to pick which series — not as a free-for-all to invent audience stereotypes for ads.

Pew notes: choose the **universe** (whole population vs subgroup) first; that choice constrains the dataset. Small samples → large error for local/subgroups. Datasets may lack variables you want (e.g. U.S. Census does **not** ask religion — Pew uses their own survey estimates for that).

---

## How this relates to our work

| Layer | Source | Role |
|-------|--------|------|
| Macro people/economy | Census / ACS / CPS (via Census or IPUMS) | Market size, age, income, employment, housing |
| Explainer / methods | This Pew page + Pew reports | How pros pick datasets; narrative context |
| Ads | Meta Ad Standards + `marketing-plan.md` | Targeting rules; no discriminatory misuse |
| Performance | Shopify + pixel | What actually converts |

**Do not** cite “Pew says buy outdoor gear if…” unless a specific Pew **report** supports it. Prefer raw Census/ACS tables for geo sizing; use Pew for **methods literacy** and published findings with links.

---

## Datasets Pew highlights (agent cheat sheet)

### 1. U.S. Decennial Census

- Hub: https://www.census.gov/programs-surveys/decennial-census/data.html  
- Full enumeration of residents (since 1790).  
- Since **2010**, the short form is mostly basic: age, sex, race, ethnicity, household relationship, homeownership.  
- Detailed characteristics now come mainly from **ACS**, not the decennial long form (ended after 2000 for that role).

**Agent use:** baseline population counts; historical context. For detailed traits → ACS.

### 2. American Community Survey (ACS)

- Hub: https://www.census.gov/programs-surveys/acs/  
- Topics: marital status, births, education, immigration/migration, income, occupation, commuting, disability, housing costs/type/value.  
- Continuous collection; covers households; since 2006 also group quarters (dorms, prisons) → full population.  
- Releases typically lag the reference year (Pew notes Sept release pattern for prior year — verify current schedule on Census site).  
- Public-use microdata often via **IPUMS USA**: https://usa.ipums.org/usa/ (1% 1-year, multi-year samples, etc.).

**Agent use:** **Primary** demographic/detail source for US market sizing (same as `notes/us-census-data.md`). Prefer multi-year ACS for small areas.

### 3. Current Population Survey (CPS)

- Hub: https://www.census.gov/cps/  
- Monthly survey (~55k households historically noted by Pew); BLS + Census.  
- Official **labor market** stats: employment, unemployment, wages.  
- Universe: civilian **noninstitutional** population (excludes prisons/nursing homes, etc.).  
- Valuable vs ACS: asks **parents’ birthplace** → immigrant **generations**.  
- **ASEC** (Annual Social and Economic Supplement, March): larger sample, income/poverty/health insurance — basis for major Census income/poverty reports.  
- Other supplements: November voting; June fertility.  
- Microdata often via **IPUMS CPS**: https://cps.ipums.org/cps/  

**Agent use:** labor/employment context; not first stop for county outdoor-gear geo maps (ACS is better for place characteristics).

### 4. Survey of Income and Program Participation (SIPP)

- Hub: https://www.census.gov/programs-surveys/sipp/  
- Longitudinal panels of households over several years.  
- Pew mainly uses for **household wealth** analysis.  
- Census issues major wealth reports from SIPP.

**Agent use:** rare for ShopifyDS Week 1 ads; only if human asks about wealth distribution narratives.

### 5. Other sources Pew lists

| Source | Typical use |
|--------|-------------|
| **UN** migration data | Global migration patterns |
| **World Bank** remittances | International money flows |
| **Survey of Consumer Finances** (Federal Reserve) | Household balance sheets / young adult debt & assets |
| **American Housing Survey** (Census + HUD) | Housing detail |
| **Consumer Expenditure Survey** (BLS/Census) | What households spend on categories |
| **BLS** employment series | Labor trends |
| **DHS** stats | Immigration administrative data |
| Foreign censuses (e.g. Mexico) | Cross-border / immigration research |

**Agent use:** CE Survey can loosely inform “category spend” stories; still not Meta targeting. Prefer store data once live.

### 6. IPUMS (Minnesota Population Center)

- ACS microdata packaging: https://usa.ipums.org/usa/  
- CPS microdata packaging: https://cps.ipums.org/cps/  
- Harmonized codes across years — good for multi-year analysis when an agent needs microdata (advanced).

---

## Research design notes from Pew (agent discipline)

1. Define **universe** before dataset (all US adults vs a subgroup).  
2. Small sample → don’t force county or tiny subgroup claims.  
3. Accept original survey **definitions** (don’t redefine variables creatively in STATUS).  
4. Missing variables → find another survey or say “not available” (don’t invent).  
5. When citing Pew **reports**, link the report URL + date; don’t only cite this methods page.

Pew homepage / topics for published findings: https://www.pewresearch.org/  

---

## ShopifyDS agent checklist

1. Methods map: https://www.pewresearch.org/data-sources-for-demographic-research/  
2. Operational US tables: https://www.census.gov/data.html + `notes/us-census-data.md`  
3. Default detail series: **ACS** (via data.census.gov or IPUMS if needed)  
4. Labor questions: **CPS** / ASEC  
5. Cite dataset + vintage + geography in task Results  
6. Do **not** turn subgroup demographics into discriminatory Meta targeting (`notes/meta-ad-standards.md`)  
7. Do **not** claim Pew endorsement of products or ad creatives  
8. Week 1 ads still blocked on creatives / FB Page / durable token — research does not launch spend  

---

## Related team docs

| Doc | Role |
|-----|------|
| `notes/us-census-data.md` | Census hub tools (QuickFacts, CBB, API) |
| `notes/demographic-tracking-agent.md` | In-repo DemographicTrackingAgent framework |
| `marketing-plan.md` | Audiences + US-only Week 1 |
| `notes/meta-ad-standards.md` | Limits on demographic use in ads |
| `MISSION.md` | Multi-niche / multi-store planning |
