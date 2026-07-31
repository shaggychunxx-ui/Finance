# Transferred positions count as deposits

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none

## Goal

All transferred positions count as deposits; zero out profit and P/L at time of deposit/transfer book-in.

## Instructions

1. Align Finance runtime P/L / capital-event rules with phone E*TRADE Trader deposit treatment (Oxygen tasks 034/035 context: transfers = deposits, $0 open P/L on transfer lots).
2. Prefer `account_profit.py` / capital-event detection on runtime Finance; mirror into git clone only if that is the source of truth and secrets stay out.
3. Document Result + clear STATUS Next line for this request.

## Done means

- Transfer book-ins do not create false profit/loss
- STATUS Next line cleared
- No secrets in git

## Cache

- Phone: "make sure all transfered positions count as deposits. zero out profit and p/l at time of deposti"
- Related Oxygen etrader v1.6.25/v1.6.26 phone display rules already shipped; Finance-side calc may still need parity.

## Do not

- Commit tokens/keys
- Disable FinanceWorkspaceWatch
