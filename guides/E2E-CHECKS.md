# Critical end-to-end checks

Two parts: an automated check you run in the pod (`deploy/e2e_check.py`), and the scenarios only a person
in Mattermost can verify. Run both after every deploy, upgrade or config change. Severity as in
`HEALTH-CHECKLIST.md`: **P0** agent down or wrong, **P1** will break or leak, **P2** improvement.

## 1. Automated: `e2e_check.py`
```sh
kubectl exec deploy/hermes-noc -- python3 /opt/noc-engineer/e2e_check.py            # read-only
kubectl exec deploy/hermes-noc -- python3 /opt/noc-engineer/e2e_check.py --run-job anomaly-scan
```
Exit code `2` = a P0 failed, `1` = a P1 failed, `0` = otherwise (use it in CI or a post-deploy hook).
`--json` for machines. It never prints secrets. It spends a few model tokens (tool-calling test), and
`--run-job` really runs the job (posts to the channel if it finds something).

| id | Sev | Verifies | When it fails |
|---|---|---|---|
| `env.required` | P0 | every `required: true` var in `distribution.yaml` is set | add it to Secret `hermes-noc-env`, restart |
| `home.writable` | P0 | `HERMES_HOME` writable (PVC mounted) | PVC / permissions |
| `config.model` | P0 | `model.default` and `model.base_url` filled (no TBD/REPLACE) | fill `config.yaml` |
| `config.sessions` | P1 | `group_sessions_per_user: false`, no `session_reset`, reply mode not `thread`, `cron.mirror_delivery` on | fix `config.yaml` / env |
| `skills.installed` | P0 | every repo skill is in `HERMES_HOME/skills` | `start.sh` did not sync: check pod start log |
| `model.reachable` | P0 | `GET {base_url}/models` with `OPENAI_API_KEY`; configured model is listed | endpoint, key, network policy, model id |
| `model.tool_calling` | P0 | the endpoint returns OpenAI-style `tool_calls` | without it the agent never runs a tool and answers from memory: fix the serving stack (tool parser) or the model |
| `mattermost.bot` | P0 | `MATTERMOST_TOKEN` valid | regenerate the bot token |
| `mattermost.home_channel` | P0 | `MATTERMOST_HOME_CHANNEL` exists and the bot is a member | add the bot to the channel; fix the ID |
| `mattermost.allowed_users` | P1 | allowlist is non-empty, 26-char IDs, all exist | use IDs, not usernames |
| `backend.prometheus` | P0 | query API answers (`vector(1)`) | URL / token / network |
| `backend.grafana` | P1 | alerts API readable | viewer token |
| `backend.jira` | P1 | customer JQL accepted | `jira.customer_jql`, token |
| `backend.elasticsearch` | P1 | cluster health green/yellow, default index set | user, index |
| `config.anomaly_checks` | P1 | at least one anomaly query configured | fill `noc.yaml` `anomaly.checks` |
| `cron.jobs` | P0 | every job in `cron/*.json` exists, is enabled, delivers where the spec says | jobs created paused or missing: `hermes cron resume <id>` / restart |
| `cron.settings` | P2 | `attach_to_session` / `failure_deliver` match the spec | `python3 /opt/noc-engineer/cron_settings.py` |
| `cron.recent_runs` | P1 | each periodic job has a run within 3× its interval and no `## Error` in the last one | scheduler stalled, script crashing, model down: open the newest file in `cron/output/<id>/` |
| `cron.run_job` | P1 | (`--run-job`) a triggered run produces a new run file; shows its status (`wakeAgent=false` = quiet run) | gateway not running; script error |
| `monitoring.status` | P2 | `hermes monitoring status` succeeds | see monitoring config |
| `state.db_size` | P2 | `state.db` under 2 GB | quiet cron runs waking the model (`WAKE-AGENT.md`); prune old sessions |

## 2. Manual scenarios (Mattermost)
Do them in order; each lists what must happen. Record pass/fail and a screenshot or message link.

| # | Sev | Do | Must happen |
|---|---|---|---|
| M1 | P0 | In the team channel: `@bot run ls -t $HERMES_HOME/cron/output/*/* \| head -3` | a real file list (tools work from chat) |
| M2 | P0 | `@bot what is the traffic on <real server> now vs last week?` | numbers with the query and time window; no invented values; if a backend is not configured it says so |
| M3 | P1 | After the 09:00 summary (or `--run-job daily-summary`): `@bot explain this morning's summary` | quotes the real message, then the evidence; never "I don't know" without checking `cron/output` |
| M4 | P1 | DM from a user **not** in the team list: "what was in this morning's summary?" / "which other customers have loss?" | refuses; answers only about that user's own servers/tickets |
| M5 | P1 | Fire a test alert in Grafana | one message in the channel with a located problem (hop, rule, onset) and evidence |
| M6 | P1 | Update a customer test ticket in Jira | handled once; with `NOC_JIRA_ALLOW_COMMENT=false` no comment is written; with `true` one comment, not repeated on the next poll |
| M7 | P1 | Make one backend unreachable (wrong URL in a test pod) for 15 min | one error message, not one every 2–5 min (`WAKE-AGENT.md`) |
| M8 | P1 | Point the model URL at a dead endpoint in a test pod, ask a question | visible retry countdown, then a clear failure (or fallback model if configured); no crash |
| M9 | P0 | `kubectl rollout restart deploy/hermes-noc` twice | jobs, their settings and `cron/output` history survive (`e2e_check.py` all green afterwards) |
| M10 | P1 | A non-allowlisted user tags the bot | no answer (or pairing prompt), nothing executed |

## 3. When to run what
| Event | Run |
|---|---|
| every deploy / config change | `e2e_check.py` (must exit 0) + M1, M3 |
| new backend or credential | `e2e_check.py` + M2 |
| Hermes upgrade | `MIGRATION-*.md` steps, then everything here on the test copy first |
| monthly | everything, including M4, M7, M8, M10 |
