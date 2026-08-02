# Role flip (2026-08-01) — option B

Human chose **inverted dual-PC roles**:

| Machine   | New role  | Does |
|-----------|-----------|------|
| **BOXONE** | **broker** | E*TRADE OAuth, headless background worker, plan build, quotes publish, orders (practice until dry_run off) |
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

4. Start **background worker** on BOXONE (headless; desktop trader UIs removed).

5. After connect, verify share updates:
   - broker/account_snapshot.json recent
   - broker/etrade_enhanced_quotes.json recent (market hours)
   - broker/broker_status.json pushed_at fresh

6. On AI-CODING (already pipeline): silent worker / pipeline loop pulls broker/* and pushes pipeline/*.

**Writer ownership (unchanged folders, swapped hosts):**
- pipeline/ writer = AI-CODING
- broker/ writer = BOXONE

Updated: 2026-08-02 (headless; push instructions to BOXONE)
