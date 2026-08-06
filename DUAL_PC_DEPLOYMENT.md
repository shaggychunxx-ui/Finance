# Dual-PC Finance deployment — RETIRED

**Status:** Obsolete for ops (2026-08-06).  
**Replacement:** [`SINGLE_HOST_GROMIT.md`](SINGLE_HOST_GROMIT.md)

**Human policy:** All Finance **off BOXONE**. GROMIT is the sole host (`role=all`).

Do not assign broker/pipeline roles to BOXONE or AI-CODING unless the human explicitly restores dual-PC.

## Single-host (active)

| Machine | `deployment.role` | Does |
|---------|-------------------|------|
| **GROMIT** | **`all`** | OAuth, worker, orders, agents, pipeline, phone bus |
| **BOXONE** | — | **No Finance** |

## Roles (generic, single-host)

`all` — single machine (use this).  
`pipeline` / `broker` — legacy dual-PC only; unused while single-host is active.

## Share

SMB FinanceShare dual-write is **optional**. Prefer local-only on GROMIT.

**Never** put `etrade_config.json`, tokens, or consumer secrets on a share or in git.
