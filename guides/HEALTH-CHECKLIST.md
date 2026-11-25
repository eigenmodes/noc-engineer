# Health checklist: Hermes NOC agent (Hermes v0.22.5, Mattermost, k8s)

## How to use (for the LLM running this)
- Go section by section. For every item run the check and record `PASS`, `FAIL` or `UNKNOWN`
  (could not check; say why).
- Do not fix anything while checking. At the end, list every `FAIL` with the proposed fix and wait for approval.
- Do not invent config keys, flags or paths. If an item does not match the running version, mark `UNKNOWN`
  and report what you found instead.
- `$HERMES_HOME` = the agent's home (`~/.hermes`, a profile under `~/.hermes/profiles/<name>`, or the
  pod's `HERMES_HOME`). Every path below is relative to it.

Severity: **P0** = the agent is down or wrong now. **P1** = will break or leak soon. **P2** = improvement.

---

## 1. Runtime
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 1.1 | P0 | `kubectl get deploy hermes-noc` | 1/1 ready | `kubectl logs`, fix the crash first |
| 1.2 | P0 | Deployment `replicas` and `strategy` | `replicas: 1`, `Recreate` | Two gateways = two chat connections and double cron runs. Set both |
| 1.3 | P0 | `HERMES_HOME` is on a PVC | sessions, memory, `cron/` survive a pod restart | Mount a PVC; otherwise every restart starts from zero |
| 1.4 | P1 | Image tag | fixed tag (no `latest`), `hermes --version` matches what was tested | Pin the tag |
| 1.5 | P0 | Entrypoint never deletes or replaces `$HERMES_HOME/cron` | no `rm -rf`/`cp -r` over that directory | It holds `jobs.json` and run output: every restart wipes jobs, their settings and history. Remove it |

## 2. Model endpoint
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 2.1 | P0 | `curl $BASE_URL/models` from the pod | 200, model id listed | Endpoint, network policy or key |
| 2.2 | P0 | Tool calling: in Mattermost `@bot run ls $HERMES_HOME/cron/output` | a real file list | Plain text with no command run = endpoint does not do OpenAI-style tool calling, or the terminal toolset is off |
| 2.3 | P1 | `config.yaml` `agent.api_max_retries`, `agent.auto_recovery_cycles` | unset (defaults 3 and 5) or set deliberately | Defaults retry 5xx, then wait 15/30/60/60/60 s with a visible countdown |
| 2.4 | P2 | `fallback_providers` | a second endpoint, if one exists | On 500/502/503 after retries Hermes switches to it mid-turn and keeps history |

## 3. Mattermost
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 3.1 | P0 | `MATTERMOST_URL`, `MATTERMOST_TOKEN` set; gateway log shows connected | connected | Token or URL |
| 3.2 | P0 | `MATTERMOST_ALLOWED_USERS` | the 26-char IDs of the team and the customers who may use it; no allow-all | Add IDs. Never `GATEWAY_ALLOW_ALL_USERS` with terminal access |
| 3.3 | P0 | `MATTERMOST_HOME_CHANNEL` | team channel ID | Cron deliveries have nowhere to go |
| 3.4 | P1 | `MATTERMOST_REPLY_MODE` | unset or `off` | `thread` = every answer in a separate thread with context cut from the channel |
| 3.5 | P1 | `config.yaml` top level `group_sessions_per_user` | `false` (written explicitly; default is `true`) | With `true`, cron messages cannot be mirrored into the channel once several people talked there |

## 4. Cron
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 4.1 | P0 | `hermes cron list` | every job present, enabled, sensible next run | Recreate from the bash script / `cron/*.json` |
| 4.2 | P0 | Each job's `deliver` | `mattermost` for channel jobs | Edit or recreate the job |
| 4.3 | P2 | Mirror on: `cron.mirror_delivery: true` (enough for `--deliver mattermost`), or per job `attach_to_session` checked with `python3 cron_settings.py --check --attach <job names>` | on | `cron list` does not show `attach_to_session`. On Mattermost v0.22.5 the mirror is best effort (see 5.3); 5.1 is what must work |
| 4.4 | P1 | Restart the pod twice, repeat 4.3 | still `OK` | Something rewrites the cron store: see 1.5 |
| 4.5 | P1 | Polling scripts print `{"wakeAgent": false}` as the last line when there is nothing new (empty stdout still wakes the model) | the model is not woken every few minutes for nothing | See `WAKE-AGENT.md` |
| 4.6 | P2 | `cron.wrap_response` | `false` if the cron header/footer is noise in the channel | Set it |
| 4.7 | P2 | `--continuity` on the daily summary (`hermes cron edit <id> --continuity`; exists in v0.22.5) | on | The summary sees yesterday's and can say what is new or resolved. Not related to chat follow-ups |
| 4.8 | P1 | `ls $HERMES_HOME/cron/output/*/` | recent run files per job | Jobs are not running: scheduler, model or script errors (`## Error` section in the run file) |

## 5. Explaining its own messages
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 5.1 | P1 | Chat skill has section `## Your own messages` | reads `cron/output/*/*` before answering about a cron message | Add it (see HERMES-UPDATE-PROMPT.md) |
| 5.2 | P1 | `SOUL.md` has the same rule in one line | present | Weak models may not load the skill; SOUL.md is always in the prompt |
| 5.3 | P2 | After a delivery: gateway debug log | `Mirror: wrote to session` | `Mirror: no session found` = no live session in the channel yet, or live sessions there (channel + threads) belong to several users. Mattermost has no thread/in_channel cron path in v0.22.5, so this lookup is the only mirror path |
| 5.4 | P1 | `@bot explain this morning's summary` | quotes the real message, then the evidence | Check 2.2, then 5.1 |
| 5.5 | P2 | Every cron message carries an ID (e.g. `[INV-0412]`) | asking by ID finds the exact file | Add the ID to the message templates |

## 6. Context and memory
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 6.1 | P2 | Long channel conversation | compressed by Hermes; someone sends `/new` in the channel when it drifts | v0.22.5 has no time-based reset (`session_reset` does not exist). Note `/new` also leaves no live session for the mirror until the next message |
| 6.2 | P2 | `memories/MEMORY.md` (cap 2,200 chars), `memories/USER.md` (cap 1,375) | durable facts only, no incident logs | Clean them; incidents belong in files, not memory |
| 6.3 | P2 | `du -h $HERMES_HOME/state.db` week over week | grows slowly | Fast growth = cron waking the model for nothing (4.5) |

## 7. Data isolation (customers talk to the bot in DMs)
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 7.1 | P1 | Team user list exists (e.g. in the environment skill) and `SOUL.md` rule: anyone not on it is a customer | present | Without it a customer DM can get internal summaries |
| 7.2 | P1 | Customer DM test: "what was in this morning's summary?", "which other customers have loss?" | refuses; answers only about that customer's servers and tickets | `cron/output`, `MEMORY.md` and `session_search` are shared by all conversations, DMs included |
| 7.3 | P1 | Does the model see who is writing? Ask in a DM: "what is my Mattermost user?" | correct user | If not, 7.1 cannot work. Full isolation = separate customer profile and bot with no team data |

## 8. Safety
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 8.1 | P1 | `config.yaml approvals` | `mode: manual`, cron/one-shot `deny`, `deny:` list blocks write commands | see `review/SECURITY.md`; "read-only" in SOUL.md alone is a prompt, not a permission |
| 8.2 | P0 | `git grep -nE "TOKEN=|PASSWORD=|sk-|pk-lf-"` in the repo | nothing | Rotate the secret, move it to the Secret |
| 8.3 | P1 | Jira write path | off by default; comments validated and de-duplicated | Turn writing off until the quality check (10) passes |

## 9. Monitoring
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 9.1 | P1 | `config.yaml` `monitoring.gateway_health_export.enabled` and `monitoring.export.otlp.enabled` | `true`, endpoint = the OTel Collector | Set them |
| 9.2 | P1 | Prometheus has `hermes_gateway_up`, `hermes_platform_up`, `hermes_cron_scheduler_heartbeat_age_seconds`, `hermes_cron_jobs_overdue` | series present | Collector pipeline or metric names after conversion |
| 9.3 | P1 | Alerts outside Hermes: gateway down/absent, platform down, scheduler heartbeat stale, overdue jobs, no successful run in 30 min | loaded (PrometheusRule) | A dead gateway cannot report itself |
| 9.4 | P2 | Langfuse | enabled only with `HERMES_LANGFUSE_CAPTURE=sanitized`; not together with another tracing plugin | Customer data must not be stored raw |

## 10. Quality
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 10.1 | P1 | 20 past alerts/tickets with a known root cause, replayed through the agent | correct hop, rule and onset in most; never invented values | Fix data access and skills before customers rely on it |
| 10.2 | P2 | Answers cite evidence (query, time range, value) | every finding | Tighten the skill instructions |

## 11. Upgrade
| # | Sev | Check | Expected | If it fails |
|---|---|---|---|---|
| 11.1 | P2 | Latest stable Hermes (v0.23.3 at time of writing) on a separate pod, then this whole checklist | all P0/P1 pass | Stay on the pinned version; v0.23 changed session handling |

---

## Report format
```
Section | # | PASS/FAIL/UNKNOWN | evidence (command + key output) | proposed fix
```
Then: P0 failures first, then P1, then P2.
