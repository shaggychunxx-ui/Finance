# Dual-PC Finance deployment

**BOXONE** runs the agent **pipeline** (always on).  
**AI-CODING** runs the **UI**, **E\*TRADE** connection, and **order placement**.  
Research and live quotes move over **SMB** (default: `\\10.10.10.1\HelperDrop\FinanceShare`).

Practice / dry-run stays **on** until you turn it off.

---

## Roles

| Machine | `deployment.role` | Does | Does not |
|---------|-------------------|------|----------|
| **BOXONE** | `pipeline` | Agents, fusion, accuracy, off-hours backtests; push research to share; pull quotes | OAuth, place orders |
| **AI-CODING** | `broker` | Unified Trader UI, E\*TRADE, plan build, swing/day orders, publish quotes | Heavy agent pipeline |
| Single PC | `all` (default) | Everything local (legacy) | — |

**Stop all / Resume** on the UI affects **trading only**. Pipeline on BOXONE keeps running.

---

## Data flow

```
BOXONE ──pipeline JSON──▶ \\10.10.10.1\FinanceShare\pipeline\ ──▶ AI-CODING output/
AI-CODING ──quotes+snapshot──▶ \\...\FinanceShare\broker\ ──▶ BOXONE output/
AI-CODING ◀── E*TRADE API (tokens local only)
```

| Share folder | Writer | Contents |
|--------------|--------|----------|
| `pipeline/` | BOXONE | Agent reports, portfolio targets, `pipeline_status.json` |
| `broker/` | AI-CODING | `etrade_enhanced_quotes.json`, `account_snapshot.json` |

**Never** put `etrade_config.json`, tokens, or consumer secrets on the share.

---

## One-time setup

### 1. AI-CODING — shared folder

**Default (no admin):** use existing HelperDrop:

```powershell
New-Item -ItemType Directory -Force -Path "C:\Users\Public\HelperDrop\FinanceShare\pipeline","C:\Users\Public\HelperDrop\FinanceShare\broker"
```

UNC: `\\10.10.10.1\HelperDrop\FinanceShare`

**Optional dedicated share** (elevated):

```powershell
cd $env:USERPROFILE\Documents\GitHub\Finance   # or $env:USERPROFILE\Finance
powershell -ExecutionPolicy Bypass -File .\Install-FinanceShare.ps1
# then set shared_root to \\10.10.10.1\FinanceShare
```

### 2. AI-CODING — broker config

In the **runtime** Finance folder (e.g. `%USERPROFILE%\Finance` — on AI-CODING after rename: `C:\Users\AI Coding\Finance`):

1. Copy `deployment.example.json` → `deployment.json`
2. Set:
   ```json
   {
     "role": "broker",
     "shared_root": "C:\\\\Users\\\\Public\\\\HelperDrop\\\\FinanceShare",
     "prefer_dry_run": true
   }
   ```
   Use the **local** path on AI-CODING (faster, no UNC loopback). BOXONE uses the UNC form.
3. In `etrade_config.json` / `short_etrade_config.json`:
   - `"dry_run": true` (practice)
   - Confirm OAuth works in **ETrade Unified Trader**
4. Start **ETrade Unified Trader** + background worker (silent worker / Install ETrade Background).

### 3. BOXONE — clean cutover (stop → uninstall → pipeline-only)

Run from the Finance install folder (often `%USERPROFILE%\Finance` or Documents\GitHub\Finance):

```powershell
cd <FinanceRoot>

# 1) Stop every pipeline/worker/GUI process + remove old autostart install
powershell -ExecutionPolicy Bypass -File .\Uninstall-FinanceApp.ps1

# 2) Pull dual-PC code
#    GitHub Desktop → Fetch/Pull   OR:
git pull origin main

# 3) Install pipeline-only (no trading GUI; worker always-on)
powershell -ExecutionPolicy Bypass -File .\Install-PipelineOnly.ps1
```

`Install-PipelineOnly.ps1` writes `deployment.json` (`role=pipeline`), forces trading flags off, installs silent worker + watchdog only, starts the pipeline, and pushes to the share.

- **No** live order placement on BOXONE (`role=pipeline` skips it).
- Tokens optional on BOXONE; quotes come from AI-CODING via the share.

### 4. Cutover checklist

1. Practice mode on **both** machines (AI-CODING already dry_run/paused for trading).
2. BOXONE: uninstall old full app autostart, then `Install-PipelineOnly.ps1`.
3. AI-CODING: connect E\*TRADE in UI, leave **dry_run true** until ready.
4. Verify share: `\\10.10.10.1\HelperDrop\FinanceShare\pipeline\` gets fresh agent JSON; `broker\` gets quotes when AI-CODING is connected.
5. When ready for live: set `dry_run` false **only on AI-CODING**.

---

## Commands

```powershell
# Manual sync
.\.venv\Scripts\python.exe sync_shared_data.py --role auto
.\.venv\Scripts\python.exe sync_shared_data.py --pull-pipeline
.\.venv\Scripts\python.exe sync_shared_data.py --push-broker

# Role override for one process
$env:FINANCE_ROLE = "broker"
$env:FINANCE_SHARED_ROOT = "\\10.10.10.1\FinanceShare"
```

---

## Market hours vs off-hours

| Session | Quotes | Pipeline focus |
|---------|--------|----------------|
| Open market | Broker publishes live E\*TRADE quotes ~every 60s | Full lanes + live enhancement from shared quotes |
| Off hours | Quotes may be stale/empty | Backtest / calibration style work (existing off-hours intervals) |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| UI agents empty | `\\10.10.10.1\HelperDrop\FinanceShare\pipeline` reachable; worker log “Shared sync” |
| Pipeline no live quotes | Broker connected; `broker\etrade_enhanced_quotes.json` recent; BOXONE can read share |
| Orders still on BOXONE | `deployment.role` must be `pipeline`; stop old full worker |
| Share access denied | Use HelperDrop path; or `Install-FinanceShare.ps1` elevated; prefer 10.10.10.x Ethernet |

---

## Files added

| File | Purpose |
|------|---------|
| `deployment.py` | Role + shared path helpers |
| `sync_shared_data.py` | Push/pull pipeline and broker feeds |
| `deployment.example.json` | Template for `deployment.json` |
| `Install-FinanceShare.ps1` | Create SMB share on AI-CODING |
| `DUAL_PC_DEPLOYMENT.md` | This guide |
