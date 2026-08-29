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

- **Pin every job's provider AND model** (`--provider` *and* `--model` at create) — the
  spend-guard watches the whole inference config, and a job pinned on only one half still counts
  as unpinned. Provider-only pinning was believed sufficient after 2026-08-24; it is not.
  On 2026-08-29 the global *model* drifted (`poolside/laguna-s-2.1:free` →
  `stepfun/step-3.7-flash:free`) and `grower_daily_report` was skipped with a pinned provider.
  Repair already-created jobs with `hermes/cron/pin-jobs.sh <provider> <model> --apply`
  (`hermes cron edit` in a loop) — **never** by re-running `setup-jobs.sh`, which creates a
  second full set of jobs rather than fixing the existing ones.
- **`--workdir` on every agent job** — without it jobs run blind (no HERMES.md).
- **healthchecks.io dead-man's switch** — the 15-min heartbeat pings it; absence of ping emails
  the owner. NEEDS OWNER: create the check, put the URL in the environment (QUESTIONS_FOR_OWNER).
- ASSUMPTION (unverified): a request-level timeout for inference may be configurable in Hermes
  Agent config — candidate knob, not yet found in the source. Next investigation step: grep the
  runtime source for client timeout defaults; if configurable, set a hard ceiling (e.g. 300 s)
  so a stalled provider fails the job (which retries + alerts) instead of hanging forever.

## Config drift — a job stopped running and nobody was told

The spend-guard alert fires **once per job**, then the job stays skipped in silence. So the
symptom you actually notice is *absence*: a report that did not arrive. Treat one drift alert as
evidence about **every** job on the host, not just the one named in it — they were all created
by the same script with the same flags.

1. `hermes cron runs` — skipped runs, and which jobs have not run since the drift.
2. `hermes config get model.provider` / `hermes config get model.model` — what the global config
   moved *to*.
3. Decide which model the jobs should be pinned to (see below), then
   `hermes/cron/pin-jobs.sh <provider> <model>` to preview, `--apply` to commit.

**Do not reflexively pin whatever the global config drifted to.** Both sides of the 2026-08-29
drift were `:free` models, and `hermes/config.yaml.example` is explicit that this deployment must
never run on a free/auto model: extraction from unpunctuated voice-note Spanish is the hardest
thing here, and a silent quality drop degrades compliance records invisibly rather than loudly.
Pin the model this deployment is supposed to run, which may not be the one the global config now
names.

## Escalation path

Job fails 3× → Hermes Agent's own `cron.failure_nudge_threshold` nudges → owner. If the
gateway itself is down, the heartbeat's MISSING ping is the alarm (healthchecks.io email).
