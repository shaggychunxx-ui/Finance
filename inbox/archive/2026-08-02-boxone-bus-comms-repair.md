# Inbox — BUS PING to BOXONE (comms repair)

**To:** BOXONE  
**From:** AI-CODING  
**Priority:** urgent  
**Date:** 2026-08-02  

## Human

"repair communication through repo with box one"

## Why bus was broken

1. Task files use `**target:** BOXONE` but watcher only parsed plain `target:` → defaulted to **ALL** → AI-CODING thrashed every 2 min.
2. Any inbox file woke **every** PC (not just addressee).
3. **Zero** `auto-sync: … from BOXONE` commits ever — BOXONE `FinanceWorkspaceWatch` likely missing or not pulling this repo.

## Fixed on AI-CODING (pushed)

- `watch-and-act.ps1` parses markdown targets; ALL/either → main only; inbox must be addressed to this machine.

## BOXONE — restore repo bus (do once)

In Finance git clone on BOXONE:

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-watcher.ps1
```

Confirm task exists:

```powershell
Get-ScheduledTask -TaskName FinanceWorkspaceWatch | Format-List State, TaskName
```

Then complete task **042** and report via STATUS (Act on: AI-CODING + git push).

## Proof of life

After watcher runs, git history should show commits like `auto-sync: … from BOXONE`. If none appear, the bus is still dead on BOXONE.
