# 059 — What is fusion %?

**status:** done  
**target:** GROMIT  
**kind:** report  
**handoff_count:** 0  
**max_handoffs:** 2  
**created:** 2026-09-05  
**updated:** 2026-09-05  
**created_by:** PHONE  
**updated_by:** GROMIT  

## Goal

Phone Send: "what is fusion %?"

## Result

**Fusion is not a hit-rate percent.** In the agent-info mail, **Fus ×** is a **vote-weight multiplier** (typical 0.55–1.25). **Acc** is the walk-forward hit rate.

Example from the mail just sent: `dca-strategy acc 43.4%  fusion 0.924` means that agent's vote counts at **0.924×** a full vote — not that fusion accuracy is 92.4% or 0.924%.

How the mail number is built (`agent_learning.fusion_multiplier`): start from walk-forward accuracy (`0.55 + acc/100 × 0.75`), then scale down for recent misses and blame, nudge up/down with edge. Boost-list agents get +12% on the trading/research blend. Range is clamped ~0.55–1.25.

That multiplier is only one factor in the live blend (`agent_fusion.fusion_weight`). Personality, calibration, domain, and accuracy floors also apply. Research exclude below **38%**; trading exclude below **40%**. Live `fusion_weights.json` (2026-09-05 02:47 UTC, regime Neutral):

| Agent | Mail Fus × | Live weight 24h/1wk/1mo |
|-------|------------|-------------------------|
| dca-strategy | 0.924 | **1.04** |
| bond-markets | 0.898 | 0.982 |
| adversarial-debate | 0.710 | 0.589 (also balance penalty) |
| equity-tracker | 0.808 | **0.0** (acc 32.5% < 38% exclude) |

**Ensemble Fusion** group Acc is `-` because `market-predictor` is not scored as directional alpha — it blends other agents.

Next agent-info PDF/body has a one-line legend: Fusion is a vote-weight multiplier, not a percent. Column header is **Fus ×**.

## Cache

- Live root `C:\Users\shagg\Finance`
- Mail number: `output/history/agent_learning.json` → `fusion_multiplier`
- Live blend: `output/history/fusion_weights.json` → `weight_24h` / `weight_1wk` / `weight_1mo`
- Helper legend: `tools/send_agent_info_email.py` (copied git → live)
- Tests `tests/test_agent_info_email.py` **6 passed**

## Do not

- Call Fusion a percent or treat 0.924 as 92.4% accuracy
- Treat Ensemble Fusion Acc `-` as missing data
- Put tokens, `account_id_key`, or SMTP passwords in git/STATUS
