# Dual-PC Finance deployment

Research and live quotes move over **SMB** (default: `\\10.10.10.1\HelperDrop\FinanceShare`).

Practice / dry-run stays **on** until you turn it off.

### Active assignment (2026-08-01 — option B, inverted)

| Machine | `deployment.role` | Does |
|---------|-------------------|------|
| **BOXONE** | **broker** | UI, E\*TRADE OAuth, plan build, orders, publish quotes to `broker/` |
| **AI-CODING** | **pipeline** | Agents, fusion, accuracy, night/full-day backtests; publish research to `pipeline/`; pull quotes |

Handoff on share: `ROLE_FLIP_B.md` and `_deploy/deployment.json.broker-for-BOXONE.json`.

### Default / original recommendation (option A)

| Machine | `deployment.role` | Does | Does not |
|---------|-------------------|------|----------|
| **BOXONE** | `pipeline` | Agents, fusion, accuracy, off-hours backtests; push research; pull quotes | OAuth, place orders |
| **AI-CODING** | `broker` | Unified Trader UI, E\*TRADE, plan build, swing/day orders, publish quotes | Heavy agent pipeline |
| Single PC | `all` (default) | Everything local (legacy) | — |

**Stop all / Resume** on the UI affects **trading only**. Pipeline host keeps researching.

---

## Roles (generic)

`pipeline` — agent research, fusion, accuracy/backtests; no order placement.  
`broker` — UI host, E\*TRADE OAuth, plan build, order placement, quote feed.  
`all` — single machine.

---

## Data flow

**Option B (active):**

```
AI-CODING ──pipeline JSON──▶ FinanceShare\pipeline\ ──▶ BOXONE output/
BOXONE ──quotes+snapshot──▶ FinanceShare\broker\ ──▶ AI-CODING output/
BOXONE ◀── E*TRADE API (tokens local only)
```

**Option A (original):**

```
BOXONE ──pipeline JSON──▶ FinanceShare\pipeline\ ──▶ AI-CODING output/
AI-CODING ──quotes+snapshot──▶ FinanceShare\broker\ ──▶ BOXONE output/
AI-CODING ◀── E*TRADE API (tokens local only)
```

| Share folder | Writer (option B) | Writer (option A) | Contents |
|--------------|-------------------|-------------------|----------|
| `pipeline/` | AI-CODING | BOXONE | Agent reports, portfolio targets, `pipeline_status.json` |
| `broker/` | BOXONE | AI-CODING | `etrade_enhanced_quotes.json`, `account_snapshot.json` |

**Never** put `etrade_config.json`, tokens, or consumer secrets on the share.

---

## One-time setup

### 1. Shared folder (usually on the machine that hosts SMB)

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

### 2. Broker machine config (option B: BOXONE)

In the **runtime** Finance folder on the broker host:

1. Copy `_deploy/deployment.json.broker-for-BOXONE.json` → `deployment.json` (or set role=broker).
2. Set `shared_root` to UNC of the share (BOXONE typically uses `\\10.10.10.1\HelperDrop\FinanceShare`).
3. In `etrade_config.json` / `short_etrade_config.json`:
   - practice: keep dry_run / prefer_dry_run true until ready
   - Confirm OAuth works in **ETrade Unified Trader**
4. Start **ETrade Unified Trader** + background worker.

### 3. Pipeline machine config (option B: AI-CODING)

1. `deployment.json`:
   ```json
   {
     "role": "pipeline",
     "shared_root": "C:\\Users\\Public\\HelperDrop\\FinanceShare",
     "publish_quotes": false,
     "consume_shared_quotes": true,
     "prefer_dry_run": true
   }
   ```
   Use the **local** path when the share is on this machine.
2. Trading flags off: `background_worker.auto_execute` / `live_trading` / `day_trading` false (role=pipeline also skips order paths).
3. Keep silent pipeline worker always-on.

### 4. Cutover checklist (option B)

1. Confirm practice mode on both machines.
2. Stop order placement on AI-CODING (role=pipeline + trading flags off).
3. On BOXONE: connect E\*TRADE, confirm account, leave dry_run true until ready.
4. Verify share: `broker/` has recent snapshot/quotes (writer=BOXONE); `pipeline/` has agent JSON (writer=AI-CODING).
5. When ready for live: set dry_run false **only on BOXONE** broker configs.

---

## Commands

```powershell
# Manual sync
.\.venv\Scripts\python.exe sync_shared_data.py --role auto
.\.venv\Scripts\python.exe sync_shared_data.py --pull-pipeline
.\.venv\Scripts\python.exe sync_shared_data.py --push-broker

# Role override for one process
$env:FINANCE_ROLE = "broker"
$env:FINANCE_SHARED_ROOT = "\\10.10.10.1\HelperDrop\FinanceShare"
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
| UI agents empty | Share `pipeline/` reachable; worker log “Shared sync” |
| Pipeline no live quotes | Broker connected; `broker\etrade_enhanced_quotes.json` recent; pipeline host can read share |
| Orders on wrong machine | `deployment.role` must be `pipeline` on the non-broker host; stop old full worker |
| Share access denied | Use HelperDrop path; or `Install-FinanceShare.ps1` elevated; prefer 10.10.10.x Ethernet |

---

## Files

| File | Purpose |
|------|---------|
| `deployment.py` | Role + shared path helpers |
| `sync_shared_data.py` | Push/pull pipeline and broker feeds |
| `deployment.example.json` | Template for `deployment.json` |
| `Install-FinanceShare.ps1` | Create SMB share |
| `Install-PipelineOnly.ps1` | Force pipeline role + trading off |
| `ROLE_FLIP_B.md` | Active inverted-role handoff |
| `DUAL_PC_DEPLOYMENT.md` | This guide |
