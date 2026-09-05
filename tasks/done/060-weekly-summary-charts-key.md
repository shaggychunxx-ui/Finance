# 060 — Send another weekly summary with charts and a term key

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

Phone Send: "send another weekly summary. go into more detail. use chars and graphs. a key with definition of terms"

## Result

Emailed **shaggychunxx@gmail.com** from GROMIT live runtime. Subject: equity **$3,955.34**, week **-4.06%**, day **-1.06%**. Body + PDF: ET week 2026-08-31–09-04 daily table, week highlights, **character charts** (`#` bars for equity / day P/L / holdings), vector **graphs** (equity line, day P/L bars, holdings week %), 16 positions with weight %, 35 open orders, **Key / definitions** (20 terms). Gmail compose **Message sent**. PDF `etrade_weekly_summary.pdf` **74,711** bytes attached (`clipboard_hdrop`). Body ink **0.24**.

## Cache

- Live root `C:\Users\shagg\Finance`
- Helper `tools/send_etrade_trader_summary_email.py` (copied git → live)
- Tests `tests/test_etrade_trader_summary.py` **10 passed**
- Last text `output/etrade_trader_summary_last.txt` (not git)
- PDF `output/etrade_weekly_summary.pdf` (not git)
- Send record `output/etrade_trader_summary_send.json` (not git)

## Do not

- Treat Gmail "Message sent" as success when the body is still the Gemini placeholder
- Omit charts or the term key — phone asked for both
- Put tokens, `account_id_key`, or SMTP passwords in git/STATUS
