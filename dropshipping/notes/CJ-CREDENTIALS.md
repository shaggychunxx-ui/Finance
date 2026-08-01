# CJdropshipping credentials (local only)

**Never put API keys, passwords, or access tokens in git / STATUS / tasks.**

## Local files (`%USERPROFILE%\.cj-link\`)

| File | Purpose |
|------|---------|
| `username` | CJ website username (e.g. `ShaggyChunxx`) |
| `password` | Website password (stored for human/agent reference; **API prefers API Key**) |
| `email` | Registered login email (optional; for legacy email+password token) |
| `api-key` | **Preferred** — API Key from CJ Authorization → API |
| `access-token` / `refresh-token` | Written by `Invoke-CJProductProbe.ps1` after successful auth |
| `token-meta.json` | Expiry metadata (no secrets beyond token files) |

## How to enable live API (human, ~2 minutes)

1. Log in at [cjdropshipping.com](https://www.cjdropshipping.com) with the stored username/password.
2. Left nav **Apps** → install **API** if not already installed.
3. **My CJ → Authorization → API** → **Add API** → Type: **API Key** → Confirm.
4. Copy the key → save as single-line file:

   ```powershell
   # On AI-CODING (example; paste key interactively, do not commit)
   Set-Content -Path "$env:USERPROFILE\.cj-link\api-key" -Value 'PASTE_KEY_HERE' -NoNewline
   ```

5. Probe:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\work\dropshipping-store\api\Invoke-CJProductProbe.ps1
   ```

## Shopify connection

The **CJdropshipping Shopify app** (install in Shopify admin for `basecampandbackwoods`) is the normal path to push supplier products and auto-fulfill. The REST API above is for agent search/list and custom automation; it does not replace the app for order fulfillment.

## Security note

If a password was ever pasted into `STATUS.md` or a commit message, **rotate it** in CJ settings after the agent has stored the new value off-git.
