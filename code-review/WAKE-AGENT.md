# wakeAgent: run the model only when a cron script found something

Verified in the Hermes v0.22.5 source (`code-review/hermes-agent`):
`cron/scheduler_prompt.py::_parse_wake_gate`, `cron/scheduler.py` (wake-gate block before `_build_job_prompt`).

## The rule
A cron job with `--script` runs the script first. Its stdout becomes the model's input. Then:

| Script result | What Hermes does |
|---|---|
| Last non-empty stdout line is exactly the JSON `{"wakeAgent": false}` | **Model not called.** No LLM tokens, no delivery, no conversation in `state.db`. A short "agent skipped" record is written to `cron/output/<job_id>/` |
| Anything else: data, non-JSON text, JSON without the flag, `{"wakeAgent": true}` | Model runs with that output as input |
| **Empty stdout** | **Model runs** (for agent jobs). Empty is silent only for `--no-agent` jobs. Quiet paths must print the flag |
| Script exits non-zero or times out | Model runs with "The data-collection script failed. Report this to the user." A crashing script posts on every run |
| Model answers exactly `[SILENT]` | Nothing delivered, but the model was already paid for |

`wakeAgent` decides whether the model runs. `[SILENT]` only decides whether its answer is sent.

## Why it matters here
`anomaly-scan` runs every 5 minutes, `grafana-alerts` every 2, `jira-tickets` every few. Most runs find
nothing. Without the flag each of them is a full model call that answers `[SILENT]`: hundreds of calls a
day, a growing `state.db`, and, with `attach_to_session`, noise in the channel conversation.

## What the scripts in this repo do (`scripts/*.py`, helper in `skills/noc-tools/scripts/noclib.py`)
| Situation | Output |
|---|---|
| New findings / alerts / tickets | the data as JSON → model runs and reports |
| Nothing new | `{"wakeAgent": false}` (`noclib.sleep_agent()`) |
| Not configured yet (TBD in `noc.yaml`) | `{"wakeAgent": false}` |
| Backend error (Prometheus, Grafana, Jira) | `{"poll_error": ...}` / `{"scan_errors": [...]}` **once**, then `{"wakeAgent": false}` for the same error for 60 minutes (`noclib.error_gate()`); a different error or the same one after an hour is reported again; recovery clears it |
| `anomaly_digest.py` (09:00) | always data: the daily summary must run |

A dead backend therefore produces one message an hour, not one every 2–5 minutes. Alerting on the agent
itself stays outside Hermes (`deploy/monitoring.yaml`).

## Writing a new cron script
1. Exit 0. Catch backend errors and turn them into an error payload; an uncaught exception wakes the model every run.
2. Every path that has nothing for the model ends with `noclib.sleep_agent()`. Never end with empty stdout.
3. Print the flag as the last line. Nothing after it.
4. Errors go through `noclib.error_gate("<job>", "<stable error text>")` so a repeating error is reported once an hour.
   Use stable text (error code and check name, not timestamps), or every run looks like a new error.
5. Call `noclib.clear_error("<job>")` after a successful poll.

## Checking it on a running system
- `ls -t $HERMES_HOME/cron/output/<job_id>/ | head` then open the newest file: quiet runs say
  `Script gate returned \`wakeAgent=false\` — agent skipped.`
- Gateway log: `Job '<name>' (ID: ...): wakeAgent=false, skipping agent run`.
- Langfuse / model endpoint: calls for `anomaly-scan` appear only when there were findings.
- Tests: `python3 -m pytest -q tests` includes `test_output_matches_hermes_wake_gate`, which runs Hermes'
  own `_parse_wake_gate` (from the submodule) on what the scripts print.
