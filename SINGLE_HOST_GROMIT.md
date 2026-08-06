# Finance single-host — GROMIT only

**Policy (human 2026-08-06):** All Finance is **off BOXONE**. Dual-PC Role flip A/B is retired for operations.

## Topology

| Machine | Finance role |
|---------|----------------|
| **GROMIT** | **Everything** — `deployment.role = all` (broker + pipeline) |
| **BOXONE** | **None** — stop workers, disable Finance scheduled tasks |
| **AI-CODING / LAPTOP** | **None** for trading |

## Live runtime (GROMIT)

```text
%USERPROFILE%\Finance
```

- Tokens / `etrade_config.json` stay **local** (never git, never share).
- Clone for bus/code: `Documents\GitHub\Finance`.

## Deployment

On GROMIT live root, `deployment.json`:

```json
{
  "role": "all",
  "prefer_dry_run": true
}
```

Share / dual-PC sync is optional and **not required** for single-host.

## Decommission BOXONE Finance

One-shot (on BOXONE when assigned via gsw bus):

1. Stop E*TRADE / Finance python workers and watchdogs.  
2. Disable scheduled tasks matching Finance / ETrade / Continuum / Pipeline.  
3. Do **not** delete tokens until human confirms backup on GROMIT.  
4. Report done to GROMIT; leave no Act on loop.

## Human OAuth on GROMIT

After cutover, complete E*TRADE OAuth **once** on GROMIT live root if tokens are not already present.
