# OXYGEN / GitStatus — verify Finance data connection (after BOXONE broker apply)

**When:** After BOXONE finishes task **042** (role=broker) and share `broker/` is fresh.
**Who:** Human on **PHONE-OXYGEN** via **GitStatus** app (Finance repo window). Never Act on PHONE.

## GitStatus checks (Finance project)

1. Open **GitStatus** → **Finance** repo (Repo List).
2. Pull / refresh STATUS — confirm you can read latest:
   - Role flip B note (BOXONE=broker, AI-CODING=pipeline)
   - BOXONE Done line for task **042** (broker applied)
3. Confirm fields load (Act on / Next / Notes) — if blank or stuck, data connection fail.
4. **Send probe** (optional but preferred): type and Send:
   `gitstatus-data-probe-verify-role-B`
   Expect AI-CODING watcher to claim and leave a RECEIPT under Done (within a few minutes).
5. Optional E*TRADE data path: open **ETrade Trader** phone app — balances/OAuth controls still load (agents feed may be gated off). Bridge is LAN; if offline on phone, note that separately from GitStatus bus.

## Pass / fail

| Check | Pass |
|-------|------|
| Finance STATUS readable in GitStatus | Yes |
| Role flip B / 042 done visible | Yes |
| Send probe gets AI-CODING RECEIPT | Yes |
| No secrets appeared in STATUS | Yes |

## After verify

- Reply in GitStatus Send: `data connection OK` or `data connection FAIL: <reason>`
- AI-CODING will mark task **043** done and clear Next.

Task: Finance `tasks/pending/043-oxygen-gitstatus-verify-data-connection.md`
