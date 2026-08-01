# Agent pipeline — collect → organize → analyze → organize → decide

**Code entry:** `buildAgentSystem().pipeline` · `src/pipeline/agentPipeline.js`  
**Mission:** `MISSION.md` — CX, revenue, quality, multi-store.

```
  INPUT BAG
      │
      ▼
 ┌─────────────┐
 │ COLLECTORS  │  all collection agents gather raw records
 └──────┬──────┘
      │
      ▼
 ┌─────────────┐
 │ DataOrganizer │  sort/index by source, type, store, supplier
 └──────┬──────┘
      │
      ▼
 ┌─────────────┐
 │  ANALYSTS   │  domain analysis (no side effects / no spend)
 └──────┬──────┘
      │
      ▼
 ┌──────────────────┐
 │ AnalysisOrganizer │  rank findings, blockers, opportunities
 └──────┬───────────┘
      │
      ▼
 ┌─────────────────┐
 │ DECISION AGENTS │  actions from analyst output only
 └─────────────────┘
```

Decisions are **proposals / holds / approved policies** in memory. They do **not** place ads, purchase inventory, or fulfill orders. Live Shopify/Meta execution stays in `api/` scripts + human/STATUS tasks.

---

## Layers

### 1. Collectors (`src/collectors/`)

| Collector | Collects |
|-----------|----------|
| `ProductCatalogCollector` | Products, tags, tracking, qty, supplier tags |
| `SupplierDataCollector` | Supplier channels + product links |
| `StorefrontSignalCollector` | Ship claims, discounts, publish state |
| `OrderSnapshotCollector` | Read-only orders (PII stripped) |
| `MarketingSignalCollector` | Creatives/Page/token/budget readiness |
| `EconomicInputCollector` | Price/cost/fees/units |
| `MultiStoreConfigCollector` | Per-store niche/budget/cap configs |
| `DemographicTrackingAgent` | Demographic profiles (existing; PII strip) |

Also available outside pipeline: `ScopeAgent`, `FileManagementAgent` (platform).

### 2. Organizers (`src/pipeline/`)

| Organizer | Job |
|-----------|-----|
| `DataOrganizer` | `bySource`, `byType`, `byStore`, `bySupplier`, indexes |
| `AnalysisOrganizer` | Severity-sorted findings, blockers, opportunities, needsHuman |

### 3. Analysts (`src/analysts/`)

| Analyst | Duty |
|---------|------|
| `CatalogLifecycleAnalyst` | Cap, untracked, OOS, create-block |
| `SupplierRoutingAnalyst` | Twins, locks, Zendrop vs CJ |
| `MarginEconomicsAnalyst` | Contribution, maxCAC, ad-viable |
| `MarketingComplianceAnalyst` | Pre-flight ads (creatives/Page/token/hero) |
| `StorefrontCxAnalyst` | Ship claim vs product, publish channel |
| `ProductInsightsAnalyst` | High margin / sales-rate performers |
| `DemographicAnalyst` | Profile completeness / segments |
| `OrderServiceAnalyst` | Open orders, revenue snapshot (human fulfill) |

### 4. Decision agents (`src/decision/`)

| Agent | Decides from |
|-------|----------------|
| `CatalogDecisionAgent` | Lifecycle analysis |
| `SupplierDecisionAgent` | Routing analysis |
| `MarketingDecisionAgent` | Compliance + margin + orders |
| `StorefrontDecisionAgent` | CX analysis |
| `MultiStoreDecisionAgent` | Store configs + caps |

---

## Usage

```js
const { buildAgentSystem } = require('./src/index');
const { pipeline } = buildAgentSystem();

const result = pipeline.run({
  products: [/* Admin API product rows */],
  economicInputs: [/* price/cost */],
  storefrontSignals: [/* claims */],
  orders: [/* optional */],
  marketing: {
    kind: 'campaign_readiness',
    heroHandle: 'mini-portable-filter-with-water-purifier-straw',
    hasCreatives: false,
    hasFacebookPage: false,
    hasDurableToken: false,
    weeklyBudgetCap: 25,
    dailyBudget: 3.5,
  },
  stores: [{ id: 'basecamp', niche: 'outdoor', status: 'live', shopDomain: '...' }],
  demographics: [/* optional segments */],
});

// Sorted data summary
console.log(result.organizedData);
// Analyst blockers first
console.log(result.organizedAnalyses.blockers);
// Decisions
console.log(result.decisions.marketing);
console.log(result.decisionSummary);
```

### Inspect layers

```js
const sys = buildAgentSystem();
console.log(sys.pipeline.describe());
```

---

## Design rules

1. **Collectors only collect** — normalize and store; no business “should we launch” logic.  
2. **Organizers only structure** — sort, index, rank severity.  
3. **Analysts only analyze** — produce findings/items/summaries.  
4. **Decision agents only decide** — read organized analyses (+ organized data when needed).  
5. **No secrets in records** — order collector strips customer PII; demographic strips direct PII.  
6. **Human gates** — fulfill, purchases, ad spend go-live when `needsHuman: true`.  

---

## Related

| Doc | Role |
|-----|------|
| `MISSION.md` | North star + profit→budget |
| `notes/platform-agents.md` | Per-account platform specialists (rules + functions) |
| `notes/demographic-tracking-agent.md` | Demo agent detail |
| `notes/meta-ad-standards.md` | Ad policy |
| `api/DROPSHIP-STACK.md` | Supplier stack |
| `marketing-plan.md` | Week 1 recipe |
