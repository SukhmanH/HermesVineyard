# Runbook — cron job hung / failed

First incident: 2026-08-24, `grower_daily_report` hung 20+ min mid-run on an inference call
that never returned (no client timeout fired). Log stops mid-session; `hermes cron runs` shows
the run stuck in `running`.

## Diagnose

1. `hermes cron runs` — stuck `running` rows, failures with tracebacks.
2. `hermes logs` — find the session id (`cron_<job>_<date>`); the last line tells you the phase
   (tool call vs API call). A long gap after `API call #N` = provider stall.
3. `hermes gateway status` — READ THE TEXT; exit code is always 0 (docs/03 §7).

## Remedy

- Restart the gateway to clear the wedged thread (WhatsApp session survives; no re-pair):
  stop the gateway process, start it again, then `hermes cron status` (ticker heartbeat fresh).
- The stuck run may still complete later and deliver — expect a possible duplicate message;
  tell the recipient it was a retry if one arrives.

## Prevention (verified where stated)

- **Pin every job's provider** (`--provider` at create) — unpinned jobs are silently SKIPPED by
  the spend-guard on any global config drift (seen live 2026-08-24). All jobs are pinned.
- **`--workdir` on every agent job** — without it jobs run blind (no HERMES.md).
- **healthchecks.io dead-man's switch** — the 15-min heartbeat pings it; absence of ping emails
  the owner. NEEDS OWNER: create the check, put the URL in the environment (QUESTIONS_FOR_OWNER).
- ASSUMPTION (unverified): a request-level timeout for inference may be configurable in Hermes
  Agent config — candidate knob, not yet found in the source. Next investigation step: grep the
  runtime source for client timeout defaults; if configurable, set a hard ceiling (e.g. 300 s)
  so a stalled provider fails the job (which retries + alerts) instead of hanging forever.

## Escalation path

Job fails 3× → Hermes Agent's own `cron.failure_nudge_threshold` nudges → owner. If the
gateway itself is down, the heartbeat's MISSING ping is the alarm (healthchecks.io email).
