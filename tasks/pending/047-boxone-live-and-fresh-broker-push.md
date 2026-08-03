# 047 — BOXONE live trading + fresh broker data for phone

**status:** pending  
**target:** BOXONE  
**kind:** broker-ops  
**depends_on:** 042  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-08-03  
**created_by:** AI-CODING  
**origin:** PHONE / human on AI-CODING  

## Goal

1. Turn **LIVE trading** on the **broker** host (BOXONE only).  
2. Pull **fresh** E*TRADE account_snapshot + quotes.  
3. Publish to FinanceShare `broker/` so AI-CODING can push a real-time phone pack.

## Context (do not skip)

| Host | Role | Orders? |
|------|------|---------|
| **BOXONE** | **broker** | **YES** — only you place orders |
| **AI-CODING** | **pipeline** | **NO** — agents only; tokens expired there |

AI-CODING already set LIVE AUTO flags on the pipeline runtime and repushed phone packs from a **stale** snapshot (`fetched_at` 2026-08-02). Phone needs **your** fresh broker feed.

## Do this on BOXONE (in order)

### A) Live trading flags

```powershell
powershell -ExecutionPolicy Bypass -File "\\10.10.10.1\HelperDrop\FinanceShare\Apply-Live-Trading-BOXONE.ps1"
```

Fallback local path if share is mapped on AI-CODING host:

`C:\Users\Public\HelperDrop\FinanceShare\Apply-Live-Trading-BOXONE.ps1`

Or bat: `Apply-Live-Trading-BOXONE.bat`

That sets: `role=broker`, `prefer_dry_run=false`, `dry_run=off`, `auto_execute=on`, `live_trading=on`, `day_trading=on`, restarts main stack.

### B) Fresh E*TRADE session (required if past midnight ET)

Tokens expire each US/Eastern midnight. If worker log says token expired:

```text
cd C:\Users\Box One\Finance
.\.venv\Scripts\python.exe begin_etrade_login.py
# complete OAuth in browser, then:
.\.venv\Scripts\python.exe finish_etrade_login.py <CODE>
```

Keep tokens **local only** — never copy to share, STATUS, or git.

### C) Force one broker cycle + publish

```text
cd C:\Users\Box One\Finance
.\.venv\Scripts\pythonw.exe etrade_worker.py --service
```

(If already running via continuum, one forced cycle is enough — restart stack from the apply script, or run a one-shot if your install supports it.)

Confirm share files are **new content** (not just mtime re-touch):

| File | Pass |
|------|------|
| `broker/account_snapshot.json` | `fetched_at` = **today** (UTC or local), positions count matches E*TRADE |
| `broker/etrade_enhanced_quotes.json` | `meta.fetched_at` recent (market hours) |
| `broker/broker_status.json` | `pushed_at` now, host BOXONE |

### D) Done markers + bus

Write:

`\\10.10.10.1\HelperDrop\FinanceShare\BOXONE_LIVE_TRADING_ON.txt`

Include: host=BOXONE, utc=…, dry_run=off, auto_execute=on, live_trading=on, snapshot_fetched_at=…, etrade_connected=True. **No secrets.**

Then update Finance **STATUS.md**:

1. Move this task → `tasks/done/047-…` with short **Result**.  
2. **Done** line: live on + fresh snapshot.  
3. **NOTIFY: AI-CODING** — live applied; snapshot fetched_at …; phone can re-pull.  
4. **Act on: AI-CODING**  
5. **Active owner: none** when you stop.

## Pass criteria

- [ ] `background_worker`: dry_run=false, auto_execute=true, live_trading=true  
- [ ] `deployment.json`: role=broker, prefer_dry_run=false  
- [ ] E*TRADE Connected production (tokens valid today)  
- [ ] `account_snapshot.fetched_at` is **today** (not 2026-08-02)  
- [ ] Share `broker/` updated; marker file present  
- [ ] STATUS NOTIFY to AI-CODING  

## Do NOT

- Paste API keys/tokens into STATUS or git  
- Act on PHONE  
- Copy tokens to AI-CODING  
- Leave dry_run=on after this task  

## Result

(empty until BOXONE completes)
