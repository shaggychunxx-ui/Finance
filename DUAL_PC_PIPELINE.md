# Dual-PC Finance pipeline (Role flip B)

| Host | Role | Responsibility |
|------|------|----------------|
| **BOXONE** `10.10.10.2` | broker | E*TRADE OAuth, headless worker, push `FinanceShare\broker\` |
| **AI-CODING** `10.10.10.1` | pipeline | Agents/fusion/backtests, push `FinanceShare\pipeline\`, pull broker |

## Data flow

```
BOXONE ──account_snapshot + quotes──▶ FinanceShare\broker\ ──▶ AI-CODING output/
AI-CODING ──agent reports + pipeline_status──▶ FinanceShare\pipeline\ ──▶ BOXONE (optional)
```

## Repo buses

1. **grok-shared-workspace** — BOXONE watcher known-good (`GrokSharedWorkspaceWatch`). Use for ops that must run on BOXONE.
2. **Finance** — trading code + Finance STATUS/tasks. Install `FinanceWorkspaceWatch` on **both** PCs.

## Health checks

- Share `broker/account_snapshot.json` mtime recent  
- AI-CODING `deployment.json` role=pipeline  
- BOXONE `deployment.json` role=broker  
- Pipeline cycles: `output/history/pipeline_runs.json` agents_total > 0  
- No tokens on share  

## One-shot on BOXONE

`\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_FINISH_042_NOW.ps1`
