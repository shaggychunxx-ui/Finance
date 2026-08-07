# OXYGEN / GitStatus — verify Finance data connection (GROMIT sole host)

**When:** Anytime after GROMIT phone bus is up (`FinanceWorkspaceWatch` + bridge optional).
**Who:** Human on **PHONE-OXYGEN** via **GitStatus** app (Finance repo window). Never Act on PHONE.

## GitStatus checks (Finance project)

1. Open **GitStatus** → **Finance** repo (Repo List).
2. Pull / refresh STATUS — confirm you can read latest:
   - **Host:** GROMIT sole Finance host (broker + pipeline + phone bus)
   - Recent Done line from GROMIT (phone reconnect / pipeline)
3. Confirm fields load (Act on / Next / Notes) — if blank or stuck, data connection fail.
4. **Send probe** (optional but preferred): type and Send:
   `gitstatus-data-probe-gromit`
   Expect **GROMIT** watcher to claim and leave a RECEIPT under Done (within a few minutes).
5. Optional E*TRADE data path: open **ETrade Trader** phone app — Setup uses LAN bridge on GROMIT:
   - Base URL: `http://192.168.1.155:8787` (Wi‑Fi; IP can change — check health on PC)
   - Token: from GROMIT live `phone_bridge_config.json` only (never paste into git/STATUS)

## Pass / fail

| Check | Pass |
|-------|------|
| Finance STATUS readable in GitStatus | Yes |
| GROMIT host note / recent Done visible | Yes |
| Send probe gets GROMIT RECEIPT | Yes |
| No secrets appeared in STATUS | Yes |

## After verify

- Reply in GitStatus Send: `data connection OK` or `data connection FAIL: <reason>`
- GROMIT will mark task **043** done and clear Next.

Task: Finance `tasks/pending/043-oxygen-gitstatus-verify-data-connection.md`
