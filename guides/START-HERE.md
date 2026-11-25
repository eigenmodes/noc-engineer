# START HERE: guide for an LLM working on this Hermes agent

Read this file first. It says what to read, in what order, and what to do for each kind of task.

## 1. What this is
- A **Hermes Agent** profile (Nous Research, pinned to **v0.22.5**) acting as the NOC engineer of a
  telecom network. It finds where a problem is (hop, rule, server, onset) and why, with evidence.
- Five jobs: anomaly scan every 5 min (now vs same time last week), 09:00 daily summary, questions in
  Mattermost (team channel and customer DMs), new Grafana alerts, customer Jira tickets.
- Runs as one pod on Kubernetes (`deploy/`), chat = Mattermost, model = an internal OpenAI-compatible
  endpoint (DeepSeek V4).
- The repo root is the profile: `SOUL.md`, `config.yaml`, `distribution.yaml`, `skills/`, `scripts/`,
  `cron/`. `deploy/`, `tests/` and `guides/` are not installed into the agent.

## 2. Ground rules (always)
1. **Never invent** config keys, CLI flags, env vars, paths, metric names or values. Verify in
   `guides/hermes-agent/` (source of the exact running version) or
   `guides/HERMES-REFERENCE-v0.22.5.md` (official docs). The source wins when they disagree.
2. Say what you verified and what you did not. "Not verified" is an acceptable answer; a guess is not.
3. Check the version first. Behavior differs between releases (see `MIGRATION-v0.22.5-to-v0.23.3.md`).
4. Production is read-only for the agent. The only write it may do is a gated Jira comment.
5. No secrets in git. They live in the k8s Secret `hermes-noc-env`.
6. Never delete or replace `$HERMES_HOME/cron/` (jobs + run history).
7. Run `python3 -m pytest -q tests` after every change. Keep the repo flat; no new services, no MCP.
8. Report to the owner (Nir) in Hebrew, bottom line first. Files for agents stay in English.

## 3. Read in this order
| # | File | Why |
|---|---|---|
| 1 | `README.md` (repo root) | layout, install, what is still TBD |
| 2 | `guides/HERMES-STRUCTURE.md` | how a Hermes project must look and what each file is for |
| 3 | `SOUL.md`, then `skills/*/SKILL.md` | what the agent is told to do |
| 4 | `config.yaml`, `distribution.yaml`, `cron/*.json`, `deploy/start.sh` | how it is configured and started |
| 5 | `guides/HEALTH-CHECKLIST.md` | what "healthy" means (P0/P1/P2) |
| 6 | `guides/review/SECURITY.md`, `guides/review/EVALS.md` | what must not happen, and how correctness is measured |
| 7 | the task-specific file from section 4 | |

Find things in Hermes: `grep -n '<key>' guides/HERMES-REFERENCE-v0.22.5.md`, then confirm in
`guides/hermes-agent/` (`grep -rn '<key>' --include=*.py guides/hermes-agent/{cron,gateway,hermes_cli}`).
If `guides/hermes-agent/` is empty: `git submodule update --init --depth 1`.

## 4. What to do, by task
| Task | Read | Do |
|---|---|---|
| **Is the agent right? (quality)** | `review/EVALS.md` | `evals/run_evals.py` on 20 known incidents, grade traces in Langfuse, fix by failure type |
| **Teach it the network (fill TBDs)** | `review/ENVIRONMENT-KNOWLEDGE.md` | hop table, anomaly checks, failure patterns, change sources, customer mapping, glossary; only values the team gives |
| **Agent misbehaves in production** | `review/RUNBOOK.md` | kill switches first (pause job, Jira off, scale 0), then triage |
| **Security review / customer isolation** | `review/SECURITY.md` | threat table with status; `config.yaml approvals` deny list |
| **Grafana dashboard** | `review/GRAFANA.md` | import `deploy/grafana/hermes-noc-dashboard.json`; metric names checked against Hermes source |
| **Explain the bot to users** | `review/USER-GUIDE.md` (Hebrew) | how to ask, what it sends, how to read status |
| **Check if the system is OK** | `E2E-CHECKS.md`, `HEALTH-CHECKLIST.md` | in the pod: `python3 /opt/noc-engineer/e2e_check.py`; then the manual scenarios; report every FAIL with its fix, fix nothing without approval |
| **Bot does not understand its own cron message** | `HERMES-UPDATE-PROMPT.md` | the reliable path is the `## Your own messages` section in `skills/customer-question/SKILL.md` (reads `cron/output`); the mirror (`cron.mirror_delivery`, `group_sessions_per_user: false`) is best effort on Mattermost v0.22.5 |
| **Answer quality of experience (format, tone, templates)** | `review/UX.en.md` | templates 3.1–3.5 into SOUL.md and skills; display settings |
| **Slow answers (thinking on, busy endpoint)** | `review/PERFORMANCE.md` | cut model rounds first (`noc.py investigate`), thinking only for chat, wakeAgent, endpoint asks |
| **Too many model calls / cost / state.db grows** | `WAKE-AGENT.md` | every quiet path of a cron script must print `{"wakeAgent": false}` as the last line; empty stdout wakes the model |
| **Add or change a cron job** | `WAKE-AGENT.md`, `HERMES-STRUCTURE.md` §3.3 | edit `cron/<name>.json` + script in `scripts/`; `attach_to_session` has no CLI flag → `deploy/cron_settings.py`; existing jobs are not changed by re-creating: use `hermes cron edit` |
| **Add a skill** | `HERMES-STRUCTURE.md` §1–2 | `skills/<name>/SKILL.md` with a `description` that says when to use it; helper code in `skills/<name>/scripts/`; add to the list in `SOUL.md`; test in `tests/` |
| **Fill the TBDs (endpoints, PromQL, JQL, hops)** | `README.md` "To fill", `skills/noc-tools/assets/noc.yaml` | only values the owner gives you; never invent queries or hostnames; then `e2e_check.py` (`backend.*`, `config.anomaly_checks`) |
| **Langfuse (deploy, connect, use)** | `review/LANGFUSE.md` | `deploy/langfuse/` (Helm values, secrets, install, bootstrap); Hermes plugin from the internal mirror via `LANGFUSE_PLUGIN_SOURCE` |
| **Monitoring / alerts on the agent** | `README.md` Monitoring, `deploy/monitoring.yaml` | OTLP export in `config.yaml`, PrometheusRule outside Hermes, Langfuse only with `HERMES_LANGFUSE_CAPTURE=sanitized` |
| **Model endpoint down / 503** | `HERMES-UPDATE-PROMPT.md` "Optional" | defaults `agent.api_max_retries: 3`, `agent.auto_recovery_cycles: 5`; `fallback_providers` only if a second endpoint exists |
| **Customer data isolation** | `review/SECURITY.md` row 5, `HEALTH-CHECKLIST.md` §7 | customers use DMs; `cron/output`, memory and `session_search` are shared across conversations → team list + rule in `SOUL.md`; verify the model sees who is writing |
| **Upgrade Hermes** | `MIGRATION-v0.22.5-to-v0.23.3.md` | backup first, test on a copy of the PVC without the bot token, one-way `state.db` migration |
| **Apply all this to another Hermes project** | `HERMES-UPDATE-PROMPT.md`, `HERMES-STRUCTURE.md` | they are written as standalone tasks; `cron_settings.py` is embedded in the first |

## 5. Facts that are easy to get wrong (all verified in v0.22.5)
- `hermes cron list` does not show `attach_to_session`; no CLI flag sets it.
- `--deliver mattermost` = home channel; `cron.mirror_delivery: true` is enough for it. Mattermost has no
  thread or in_channel cron surface, so the mirror lands only if the channel has one live session.
- `group_sessions_per_user` defaults to `true`; deleting the line does not make it false.
- There is **no** `session_reset` in v0.22.5 (core ignores it). Reset is `/new` or `/reset` in chat.
- Empty script stdout **wakes** the model for agent jobs.
- `--continuity` gives a job its own previous output; it is not chat continuity.
- `--failure-deliver` exists as a CLI flag.
- `SOUL.md` loads from `HERMES_HOME` only; a `CLAUDE.md`/`AGENTS.md` in the agent's working directory is
  loaded into the bot as project context.

## 6. How to finish a task
1. Tests pass (`python3 -m pytest -q tests`).
2. If behavior changed: update the matching file in `guides/` and `README.md`.
3. Commit with a message that says what changed and what was verified against which version.
4. Report: what changed, what was verified, what was not, the next step (one), in Hebrew.

## Files in this folder
| File | Purpose |
|---|---|
| `START-HERE.md` | this guide |
| `review/` | latest guides, not yet reviewed by the owner (see `review/README.md`) |
| `HERMES-STRUCTURE.md` | target structure, steps, "done means" |
| `HEALTH-CHECKLIST.md` | full health checklist P0/P1/P2 |
| `E2E-CHECKS.md` | `e2e_check.py` explained + manual Mattermost scenarios |
| `WAKE-AGENT.md` | when cron wakes the model, how to write cron scripts |
| `HERMES-UPDATE-PROMPT.md` | task: bot explains its own cron messages (standalone, for other projects too) |
| `MIGRATION-v0.22.5-to-v0.23.3.md` | upgrade path and rollback |
| `review/LANGFUSE.md` | Langfuse deploy + Hermes connection, end to end |
| `review/PERFORMANCE.md` | speed with thinking on: rounds, profiles, endpoint, UX |
| `review/UX.en.md` | premium user experience: answer templates, ack, behavior, audience, metrics (Hebrew copy: `review/UX.md`) |
| `review/EVALS.md` | quality: case set, runner, grading, fixes |
| `review/ENVIRONMENT-KNOWLEDGE.md` | what network knowledge to collect and where it goes |
| `review/RUNBOOK.md` | kill switches, triage, symptoms, rollback |
| `review/SECURITY.md` | threats, controls, gaps, rotation |
| `review/GRAFANA.md` | dashboard import and alerts |
| `review/USER-GUIDE.md` | for the team and customers (Hebrew) |
| `HERMES-REFERENCE-v0.22.5.md` | official Hermes docs, 24 pages, grep it |
| `hermes-agent/` | Hermes source at v0.22.5 (submodule) |
