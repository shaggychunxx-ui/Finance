# Role flip (2026-08-01) — option B

Human chose **inverted dual-PC roles**:

| Machine   | New role  | Does |
|-----------|-----------|------|
| **BOXONE** | **broker** | E*TRADE OAuth, Unified Trader UI, plan build, quotes publish, orders (practice until dry_run off) |
| **AI-CODING** | **pipeline** | Agents, fusion, accuracy, night/full-day backtests; pull quotes from share; **no** order placement |

Applied on AI-CODING already:
- deployment.json role=pipeline
- etrade configs: auto_execute/live/day trading OFF, dry_run true

## BOXONE steps (do once on BOXONE)

1. Copy this into BOXONE Finance runtime as deployment.json:
   _deploy/deployment.json.broker-for-BOXONE.json
   (or set role=broker + shared_root=\\10.10.10.1\HelperDrop\FinanceShare)

2. Keep OAuth tokens **local on BOXONE only** (already connected). Never copy tokens to share or git.

3. Confirm practice mode: background_worker.dry_run=true until ready for live.

4. Start **ETrade Unified Trader** + background worker on BOXONE.

5. After connect, verify share updates:
   - roker/account_snapshot.json recent
   - roker/etrade_enhanced_quotes.json recent (market hours)
   - roker/broker_status.json pushed_at fresh

6. On AI-CODING (already pipeline): silent worker / pipeline loop pulls broker/* and pushes pipeline/*.

**Writer ownership (unchanged folders, swapped hosts):**
- pipeline/ writer = AI-CODING
- roker/ writer = BOXONE

Generated: 2026-08-01T10:54:30.834113+00:00
