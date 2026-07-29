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
cd $env:USERPROFILE\Documents\GitHub\Finance   # or C:\Users\Box One\Finance
powershell -ExecutionPolicy Bypass -File .\Install-FinanceShare.ps1
# then set shared_root to \\10.10.10.1\FinanceShare
```

### 2. AI-CODING — broker config

In the **runtime** Finance folder (e.g. `C:\Users\Box One\Finance`):

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

### 3. BOXONE — pipeline config

1. Git pull / GitHub Desktop update of Finance
2. `deployment.json`:
   ```json
   {
     "role": "pipeline",
     "shared_root": "\\\\10.10.10.1\\HelperDrop\\FinanceShare"
   }
   ```
3. **No** need for live tokens on BOXONE for dual-PC mode (quotes come from the share).
4. Keep worker always-on: **Start Silent Worker Only** / existing background install.
5. **Stop** order placement on BOXONE: set `background_worker.auto_execute` / `live_trading` / `day_trading` false **or** rely on `role=pipeline` (trading paths skipped).

### 4. Cutover from “live on BOXONE”

1. Confirm practice mode on **both** machines.
2. Stop live trading on BOXONE (Stop all / pause + role=pipeline).
3. On AI-CODING: connect E\*TRADE in UI, confirm account, leave **dry_run true**.
4. Verify share: after a cycle, `\\10.10.10.1\HelperDrop\FinanceShare\pipeline\` has agent JSON and `broker\` has quotes.
5. UI Agents tab on AI-CODING shows reports from the share pull.
6. When ready: set `dry_run` false **only on AI-CODING** broker configs.

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
