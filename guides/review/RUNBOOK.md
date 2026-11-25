# Runbook: when the agent itself misbehaves

For whoever is on call for the agent. Commands assume `kubectl` access to the namespace of
`deploy/hermes-noc`; `H=kubectl exec deploy/hermes-noc --`.

## Kill switches (fastest first)
| Need | Do | Undo |
|---|---|---|
| Stop one noisy job | `$H hermes cron pause <job_id>` (`$H hermes cron list` for ids) | `hermes cron resume <job_id>` |
| Stop all scheduled work, keep chat | pause every job | resume them |
| Stop Jira comments | set `NOC_JIRA_ALLOW_COMMENT=false` in Secret `hermes-noc-env`, `kubectl rollout restart deploy/hermes-noc` | set `true` |
| Stop answering a customer / user | remove the ID from `MATTERMOST_ALLOWED_USERS`, restart | add back |
| Stop everything | `kubectl scale deploy/hermes-noc --replicas=0` | `--replicas=1` (data stays on the PVC) |
| Cut it off from Mattermost entirely | deactivate the bot account or revoke its token in Mattermost | new token in the Secret |

Pausing keeps the job and its history; never delete `$HERMES_HOME/cron/`.

## Triage (5 minutes)
1. `$H python3 /opt/noc-engineer/e2e_check.py` → which layer fails (model, Mattermost, backend, cron).
2. Grafana dashboard **NOC agent (Hermes)**: gateway up, platform up, heartbeat, last success.
3. `kubectl logs deploy/hermes-noc --tail=200` and `$H tail -n 200 $HERMES_HOME/logs/agent.log`.
4. Last runs of a job: `$H ls -t $HERMES_HOME/cron/output/<job_id>/ | head`, open the newest
   (`## Error` section = what failed).
5. A wrong answer: its trace in Langfuse (which tools ran, what came back).

## Symptoms
| Symptom | Likely cause | Action |
|---|---|---|
| Channel flooded with the same finding | cooldown too short, flapping metric, or state lost (PVC) | pause `anomaly-scan`; check `data/noc/anomaly_state.json`; raise `cooldown_minutes` or `min_baseline` |
| Same backend error every few minutes | error gate state lost or error text not stable | pause the job; see `../WAKE-AGENT.md`; fix the backend |
| No messages at all | gateway down, Mattermost disconnected, bot not in channel, jobs paused | `e2e_check.py` (`mattermost.*`, `cron.jobs`) |
| Messages stop after a restart | jobs recreated paused or deleted | `hermes cron list`; `cron.jobs` check; `start.sh` log |
| Answers from memory, no numbers | tool calling broken or terminal toolset off | `e2e_check.py model.tool_calling`; Langfuse trace has no tool spans |
| Invented values / wrong hop | knowledge gap or skill | stop customer use if it reached a customer; add an eval case; `ENVIRONMENT-KNOWLEDGE.md` |
| Told a customer something internal | isolation failure | remove the customer from the allowlist, inform the team lead, `SECURITY.md`, add a `forbid` eval case |
| "Model unavailable" / long retries | endpoint down or overloaded (503) | model team; dashboard model row; `fallback_providers` if a second endpoint exists |
| Very slow answers | model latency, many tool round-trips, huge context | dashboard; Langfuse latency per span; `/new` in the channel if the conversation is huge |
| Pod restarts | OOM, crash at start | `kubectl describe pod`, memory panel, `start.sh` output |
| `state.db` large / disk full | quiet cron runs waking the model | `../WAKE-AGENT.md`; PVC size |

## Rollback
| What changed | Roll back |
|---|---|
| Skill, SOUL, config, scripts (git) | `git revert <commit>`, rebuild image, `kubectl set image ...` (start.sh re-syncs files) |
| Image / Hermes version | `kubectl set image deploy/hermes-noc hermes=<previous tag>`; after a Hermes upgrade only with a PVC restore (`../MIGRATION-*.md`) |
| A job's settings | `hermes cron edit <id> ...` or `cron_settings.py` |

## After an incident
1. Short write-up: what the agent did, who saw it, impact, cause, fix.
2. Add an eval case that reproduces it (`EVALS.md`).
3. If a guard was missing, add it (alert, deny rule, `forbid`, test).
