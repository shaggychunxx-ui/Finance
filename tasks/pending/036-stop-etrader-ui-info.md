# Stop sending info to etrader UI

target: AI-CODING
origin: PHONE
kind: work
handoff_count: 0
max_handoffs: 2
parent: none

## Goal

Honor phone request: stop sending info to the E*TRADE Trader phone UI (etrader).

## Instructions

1. Identify what still pushes data to the etrader phone UI (phone_bridge `/api/agents`, agent report publish, continuum hooks, Oxygen-OS `work/phone/etrade-agents.json` builders, etc.).
2. Disable or gate **outbound phone UI info** without breaking PC trading unless STATUS asks for that.
3. Prefer config/flag over deleting code; no secrets in git.
4. Document what was stopped and how to re-enable in task Result + STATUS Done.

## Done means

- Clear description of what was stopped
- Next line for this request cleared
- STATUS Done + NOTIFY if BOXONE hosts bridge

## Cache

- Phone request sat in Next while Act on was cleared without work (no Finance watcher).
- Runtime bridge: often `C:\Users\Box One\Finance\phone_bridge.py` (not always in this clone).
- Etrader UI agents bus also uses Oxygen-OS `work/phone/etrade-agents.json`.

## Do not

- Commit API keys / bridge tokens
- Disable FinanceWorkspaceWatch
- Blindly kill all E*TRADE workers without confirming scope is **phone UI info only**
