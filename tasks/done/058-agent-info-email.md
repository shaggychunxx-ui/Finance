# 058 — Send email of details agent info

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

Phone Send: "send email of details agent info"

## Result

Emailed **shaggychunxx@gmail.com** from GROMIT live runtime. Subject: **73 agents**, top **dca-strategy 43.4%**. Body + PDF: roster (catalog 76 / learning 73 / phone pack 83), learning health (live scored rows **0**, walk-forward merged 25000), last pipeline, next-session brief, boost/cut policy, group averages, top/weak agents, current directional calls, full agent table. Gmail compose **Message sent**. PDF `etrade_agent_info.pdf` **119,809** bytes attached (`clipboard_hdrop`). Body ink **0.21**.

Accuracy in this mail is walk-forward + sticky live_accuracy — not matured live 24h labels.

## Cache

- Live root `C:\Users\shagg\Finance`
- Helper `tools/send_agent_info_email.py` (copied git → live)
- Reuses Gmail send path in `tools/send_etrade_trader_summary_email.py`
- Tests `tests/test_agent_info_email.py` **6 passed**
- Last text `output/etrade_agent_info_last.txt` (not git)
- PDF `output/etrade_agent_info.pdf` (not git)
- Send record `output/etrade_agent_info_send.json` (not git)

## Do not

- Treat Gmail "Message sent" as success when the body is still the Gemini placeholder
- Omit the PDF — phone previously asked for an attachment
- Put tokens, `account_id_key`, or SMTP passwords in git/STATUS
- Call this live accuracy when `live_scored_rows` is 0
