# 048 — Continue pipeline repair (phone pull + trading gate)

**Target:** AI-CODING  
**Origin:** human interactive  
**Status:** done  
**Completed:** 2026-08-04

## Problem

1. Phone live pull always used `accounts[0]` → secondary **#6854** (1 lot SPCX) instead of selected **#8804** (14 lots). Quality gate logged `live pull thinner (1 < prior 14)` and never refreshed live.
2. Trading gate eligibility used cost-aware `combined_accuracy_pct` with a **40%** floor → **0/72** agents eligible. Strategy plan BUYs all blocked (`no_accuracy_data` / cluster fail). Portfolio fell back to pre-gate candidates only.

## Changes

- `phone_bridge.py` (v1.5.6): resolve account via `get_selected_account`; match label from `list_accounts`; log selected account; clearer thinner-pull message.
- `trading_gate.py`: `_eligibility_accuracy_pct` (preferred-horizon / direction / combined max); default `min_accuracy_pct` **35.0**.

## Verify

- Live pull force → **14** positions on #8804, `live=True`.
- Eligibility → **12** agents (markets, finance, datascience, …).
- Force eco pipeline critical+quant → **10/10** PIPELINE_OK.
- Plan rebuild → **15 proposed**, **0 blocked**; gate candidates **19/19** passed.
- Unit: `test_trading_gate_cluster_and_eligibility` passed.

## Result

Pipeline + phone data path repaired for LIVE on AI-CODING role=all. Orders still wait for RTH. No secrets committed.
