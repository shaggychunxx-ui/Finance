# Dual-PC repo bus (AI-CODING ↔ BOXONE)

How the two PCs talk: **git only** (STATUS / tasks / inbox). SMB `FinanceShare` is for trading data, not agent assignment.

## Protocol

| Field | Meaning |
|-------|---------|
| **Act on:** `AI-CODING` / `BOXONE` / `none` | Which machine’s watcher may run headless Grok |
| **Active owner:** | Who is currently working (set while claiming) |
| **NOTIFY X:** | One-shot message for the other PC |
| `tasks/pending/*.md` | Work items; **must** include `target: BOXONE` or `target: AI-CODING` |
| `inbox/*-boxone-*.md` | Message **to BOXONE** (filename or `To: BOXONE`) |
| `inbox/*-ai-coding-*.md` | Message **to AI-CODING** |

**Never** `Act on: PHONE`. Phone uses GitStatus Send → STATUS Next lines for AI-CODING.

## Watcher (required on BOTH PCs)

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance   # or your clone path
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-watcher.ps1
Get-ScheduledTask -TaskName FinanceWorkspaceWatch
```

Task runs every ~2 minutes: `git pull` → if assigned → headless Grok → may `auto-sync: … from <MACHINE>` push.

### Proof the bus is alive

| Machine | Healthy sign |
|---------|----------------|
| AI-CODING | `auto-sync: … from AI-CODING` commits; `.local/watch.log` updates |
| BOXONE | **`auto-sync: … from BOXONE` commits** (if none ever, BOXONE watcher is dead) |

## 2026-08-02 repair (AI-CODING)

**Bugs fixed in `watch-and-act.ps1`:**

1. Task lines like `**target:** BOXONE` failed to parse → treated as **ALL** → main PC thrashed every cycle.
2. Any file in `inbox/` woke **every** machine.
3. `ALL` / `either` now wake **AI-CODING only** (helper must get explicit Act on / target).
4. `PHONE` / `OXYGEN` targets never wake PCs.
5. If **Act on** is the *other* PC, pending/inbox noise no longer wakes you unless the item targets you by name.

**Ops cleanup:** stale inbox mail archived under `inbox/archive/`. One live ping: `inbox/2026-08-02-boxone-bus-comms-repair.md`.

## BOXONE checklist after this repair

1. `git pull` Finance  
2. Install/repair watcher (`install-watcher.ps1`)  
3. Confirm `FinanceWorkspaceWatch` exists and runs  
4. Wait one cycle — push should appear as `from BOXONE` if local dirty, or Grok should act when **Act on: BOXONE**  
5. Finish task **042** and hand off **Act on: AI-CODING** + push  

## Anti-thrash

- Idle assignee: exit with **zero** STATUS edits  
- One NOTIFY per completion; receiver acks once then `Act on: none`  
- Do not leave multi-day inbox piles addressed to everyone  
