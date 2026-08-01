# Meta Model API — pricing & rate limits

**Source:** [dev.meta.ai — Pricing and rate limits](https://dev.meta.ai/docs/getting-started/pricing-rate-limits/)  
**Captured:** 2026-07-28 by AI-CODING (PHONE request)  
**Scope:** Meta **Model API** (LLM / Muse Spark / OpenCode) — **not** Facebook/Instagram Marketing API ads.

---

## Pricing (USD per 1M tokens)

| Usage | Price / 1M tokens |
|-------|-------------------|
| Input | **$1.25** |
| Cached input | **$0.15** |
| Output | **$4.25** |

- Pay only for what you use; no minimums / no upfront commitment.
- **Cached input** is cheaper when a prompt prefix hits [prompt caching](https://dev.meta.ai/docs/prompt-caching); check `cached_tokens` in the response.
- **Web search grounding:** **$2.50 per 1,000 search queries** *in addition* to token cost for that request.
- **No long-context premium** — same token rates whether the window is empty or nearly full.
- Meta injects a small steering system prompt; those injected tokens are **not billed** and are excluded from reported usage.

## Rate limits (per team, not per key)

| Tier | Requests / min (RPM) | Tokens / min (TPM) |
|------|----------------------|--------------------|
| Free | 60 | 2,000,000 |
| Paid | 3,000 | 4,000,000 |

- Multiple API keys in one team share **one** quota.
- Over limit → `HTTP 429`; wait until usage drops; use exponential backoff + jitter (e.g. start ~500 ms).
- Useful headers: `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`.
- **Background responses** (`background: true`): separate cap — default **600 submissions / min / team** (plus normal RPM/TPM). Over cap → 429 with `Retry-After`.

## ShopifyDS notes

| Item | Status |
|------|--------|
| Where key lives | `~\.meta-link\model-api-key` only (never git / STATUS) |
| OpenCode on AI-CODING | 1.18.9 · model `meta/muse-spark-1.1` |
| Ads / Marketing API | **Separate** — this doc does not unlock Meta Ads Manager spend |
| Cost risk | Model API token bills are **LLM usage**, not the $25/wk ad budget in `marketing-plan.md` |

Keep Model API spend light for coding agents; ad budget remains the marketing plan ($25/wk) once Marketing API + creatives exist.
