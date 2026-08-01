# DemographicTrackingAgent — agent knowledge

**Code:** `src/demographicTrackingAgent.js`  
**Tests:** `test/demographicTrackingAgent.test.js`  
**Exposed via:** `buildAgentSystem().demographicTrackingAgent` in `src/index.js`

Demographic tracking is the foundational blueprint for understanding populations and driving strategic decisions across commercial, public infrastructure, and digital ecosystems. This agent encodes that framework for **ShopifyDS** (Basecamp and multi-store planning).

---

## What it does

| Method | Purpose |
|--------|---------|
| `getBlueprint()` | Full framework: pillars, pipelines, sectors, guardrails, ShopifyDS defaults |
| `monitor(records)` | Pillar coverage + PII flags without storing |
| `collectData(records)` | Store segment profiles; **strips direct PII by default** |
| `research(record)` | Completeness score, missing variables, recommendations |
| `assessPrivacy(record)` | GDPR/CCPA-minded flags; never “ok” for Meta personal-attribute ad assertions |
| `filterByGeography` / `filterByCohort` | Segment filters |
| `summarizeSegments()` | Counts by cohort/country |
| `recommendForShopifyDs()` | US-first, ACS/public baselines, Week 1 audience hints |

---

## Core data pillars

1. **Socioeconomic** — householdIncome, educationalAttainment, occupationalStatus  
2. **Geographic** — macroLocation, microLocation, mobilityPatterns  
3. **Psychographic** — languagePreferences, householdComposition, generationalCohort  
4. **Collection context** — sourcePipeline, consentOrPublic  

## Collection pipelines

- **firstPartyDigital** — registration, behavioral inference, SSO (needs disclosure)  
- **macroPublic** — censuses, registries, statistical sampling (preferred baselines)  
- **offlineRealWorld** — POS/loyalty, opt-in location (not Week 1 default)  

## Guardrails

Regulatory compliance (GDPR/CCPA), anonymization, differential privacy concepts, **Meta Ad Standards** (no discriminatory targeting / personal-attribute ad copy).

---

## External sources (do not reinvent)

| Doc / URL | Role |
|-----------|------|
| https://www.census.gov/data.html · `notes/us-census-data.md` | Operational Census tools |
| https://www.pewresearch.org/data-sources-for-demographic-research/ · `notes/pew-demographic-data-sources.md` | Dataset methods map |
| `notes/meta-ad-standards.md` | Ad use limits |
| `marketing-plan.md` §1 | Week 1 audiences |

---

## Privacy

- Direct PII keys (email, phone, SSN, names, street address, device IDs, etc.) are **stripped on collect** unless `anonymizeOnCollect: false`.  
- Prefer **public aggregates** (ACS) for income/education bands over collecting first-party income.  
- Never put PII in git or STATUS.

---

## Workflow questions (from framework)

When a human asks for demographic work, clarify:

1. **Ultimate goal/choice** — ads, merchandising, multi-store geo, policy-style research?  
2. **Tool vs policy** — need Census/Pew tables, agent API usage, or a written collection policy?

Defaults for this repo: **private-sector ads + merchandising**, US-first, public baselines + consented first-party only.

---

## Quick code usage

```js
const { buildAgentSystem } = require('./src/index');
const { demographicTrackingAgent: demo } = buildAgentSystem();

const blueprint = demo.getBlueprint();
demo.collectData([
  {
    id: 'us-millennial-outdoor',
    householdIncome: '75000-99999',
    macroLocation: { country: 'US', state: 'CO' },
    generationalCohort: 'millennial',
    languagePreferences: ['en'],
    sourcePipeline: 'macroPublic',
    consentOrPublic: 'public_aggregate',
  },
]);
console.log(demo.summarizeSegments());
```
