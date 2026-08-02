# Inbox — BOXONE finish 042 and report to AI-CODING

**From:** AI-CODING  
**To:** BOXONE  
**Priority:** do now — complete handoff  
**Task:** 042  
**Date:** 2026-08-02  

## Human instruction

"Tell box one to finish and to inform you when complete. Work together like you are supposed to."

## AI-CODING verification (still incomplete)

- No `BOXONE_BROKER_APPLY_DONE.txt`
- Share `broker/account_snapshot.json` still ~Jul 30
- STATUS never closed by BOXONE

## BOXONE must do

1. Apply script + headless worker + **fresh** share `broker/`
2. **Inform AI-CODING** via STATUS:
   - Done line for 042
   - `NOTIFY AI-CODING: 042 complete...`
   - **Act on: AI-CODING**
   - git push

AI-CODING will then ack once, confirm share, set Act on: none, leave PHONE **043** for human GitStatus.
