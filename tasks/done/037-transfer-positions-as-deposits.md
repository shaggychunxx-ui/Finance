# Transferred positions count as deposits

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none
status: done
completed: 2026-07-31
completed_by: AI-CODING

## Goal

All transferred positions count as deposits; zero out profit and P/L at time of deposit/transfer book-in.

## Result

**Done.** Live account metrics confirm transfer book-in is capital, not trading P/L.

### Detection (account_profit.py — git + runtime)
- Cash-matched wires → deposit
- Cash-flat equity jumps → **`acats_transfer`** deposit
- ≥50% equity capital-events → deposit (mixed ACATS)
- Manual overrides: `output/manual_external_flows.json`
- Formula: `profit = latest − opening − net_external_flows`

### Position-level (runtime phone_bridge v1.3.6)
- Transfer symbols loaded from defaults **SPCX+SAGMF**, `position_cost_overrides.json` (`transfer_as_deposit`), and learned `transfer_deposit_symbols.json`
- Open P/L forced **$0** / display **Deposit** on transfer lots; HOLD only
- Newly flagged symbols auto-persisted

### Live verify (AI-CODING runtime)
- net_external_flows ≈ **$3,696.19** (includes ACATS **$1,502.19** on 2026-07-30)
- total_pl ≈ **−$17.55** (not +$1.5k false profit)
- Events include `acats_transfer` + `capital_event` sources

### Git
- `account_profit.py` synced (capital-event / ACATS)
- `tests/test_account_profit_transfers.py` (6 tests, all pass via direct run)

## Do not
- Commit tokens/keys
- Disable FinanceWorkspaceWatch
