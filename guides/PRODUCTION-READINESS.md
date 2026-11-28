# Production readiness — harden the existing NOC agent (for the implementing LLM)

**Goal:** make the agent that runs today production-grade. Do NOT build a new system.

Today's agent:
- Hermes gateway, Mattermost (team channel + DMs), DeepSeek V4 (internal).
- Cron jobs: anomaly scan (5 min), 09:00 summary, Grafana poll, Jira poll (in rollout).
- Scripts with the wakeAgent gate, approvals config, monitoring, Langfuse, `e2e_check`, evals.

Rules:
- Work through the items in order. For each item: inspect → report what exists → change only the gap → verify.
- Never invent Hermes keys or flags. Check every key against the deployed version's source or docs
  (`guides/HERMES-STRUCTURE.md` says where to look).
- Do not change `group_sessions_per_user: false`.
- No new services (queue, DB, workers) unless an item below says so.
- After each item, append one line to `PRODUCTION-STATUS.md`: item, before, change, how it was verified.

`guides/review/INVESTIGATION-ORCHESTRATION.md` is a reference for a possible future stage. It is NOT part of this task.

---

## P0 — Session isolation and stability under load (the owner's top priority)

The owner must be able to state, with evidence, that information does not mix between sessions and that
the bot stays stable when many users talk to it at once. Prove both with the tests below. Do not assert them.

**What is isolated and what is shared.** Verified in the v0.22.5 source; re-verify on the deployed version and
write the result into `PRODUCTION-STATUS.md`.

| Layer | Scope | Mixing risk |
|---|---|---|
| Conversation history | Per session key (`gateway/session.py::build_session_key`): DM = per user; channel = shared (by design, `group_sessions_per_user: false`); thread = per thread | None between DMs. Inside a channel, sharing is intended |
| Persistent memory (`memory.memory_enabled`, user profile) | Per PROFILE, injected into EVERY session | **Yes.** A fact saved in DM A can appear in DM B. Decision 5.4 |
| Same-session concurrent messages | `display.busy_input_mode` (default `interrupt`) | Two requests in one session get merged/redirected. Fix 2.1 |
| Cron deliveries | `cron.mirror_delivery` / `attach_to_session` write the job output into the target session's history | Intended for the home channel. Make sure no job targets a customer DM |
| Files under `HERMES_HOME/data/` | Shared by all jobs and sessions | Each job writes only its own paths. No user content in shared files |
| Reply routing | The reply goes back to the originating chat/thread | Verify under load (test I-3) |

**Isolation tests (run on a test bot or a quiet hour; record results):**
- I-1: Two DMs at the same time with different topics (user A asks about server X, user B about rule Y).
  Each answer mentions only its own topic.
- I-2: In DM B ask "מה המשתמש השני שאל?" / "what did others ask you today?". It must not reveal A's conversation.
- I-3: Send 8 DMs within 10 seconds, each with a unique marker word. Each reply arrives in the right DM and
  contains only its own marker. No reply is lost.
- I-4 (memory): in DM A tell the bot a fake fact ("the code for customer Z is 4711"). Later, in DM B, ask for it.
  If it leaks, memory is shared → apply decision 5.4. Delete the fake fact afterwards.
- I-5: Two messages in the same channel 2 seconds apart. With `busy_input_mode: queue` both are answered in
  order, without one cutting off the other.

**Load and stability tests (record numbers):**
- L-1: 8 concurrent DMs + 1 channel question while the anomaly scan runs. Record: time to first reply, time to
  final answer, LLM errors/503s, fallback activations, gateway CPU/memory.
- L-2: 15 concurrent DMs. The gateway must not crash or restart. Every user gets an answer or a clear error.
  No silent drops.
- L-3: Kill the LLM primary during L-1 → answers continue via the fallback (P3).
- L-4: Restart the gateway pod during a running answer → after restart the bot answers again. Record what happened
  to the interrupted turn.
- Pass criteria: no crash, no lost or cross-routed replies. The owner sets the latency targets from the measured
  numbers, and they are recorded.

---

## P1 — Deployment safety

| # | Check | Required state | Verify |
|---|---|---|---|
| 1.1 | Hermes version | Known, written in `PRODUCTION-STATUS.md`; image pinned by exact tag or digest, never `latest` | `hermes --version` in the running container = tag in the manifest |
| 1.2 | Instances | Exactly one gateway per `HERMES_HOME` (one `state.db`). k8s: `replicas: 1` + `strategy: Recreate`. A rolling update briefly runs two gateways → double cron runs, two Mattermost connections | Manifest; during a redeploy, the old pod ends before the new one starts |
| 1.3 | Persistent state | `HERMES_HOME` on a persistent volume: sessions, memory, cron state, `data/` | Restart the pod → the next answer still knows the earlier thread |
| 1.4 | Probes | liveness + readiness. Use what the deployed version exposes (health endpoint, or `hermes status`, or the `hermes_gateway_up` metric). Do not invent an endpoint | Kill the process → k8s restarts it |
| 1.5 | Secrets | All tokens in k8s Secrets / env. None in git, config.yaml, logs or Langfuse | `git grep` for tokens; inspect one Langfuse trace |
| 1.6 | Backup | Daily backup of `state.db` + `HERMES_HOME/data`. Mandatory before any upgrade (the 0.22.5→0.23.3 schema change is one-way) | Restore into a scratch pod once and start it |
| 1.7 | Upgrade path | `guides/MIGRATION-v0.22.5-to-v0.23.3.md` followed; a rollback = previous image + restored backup | Dry run in a test namespace |

## P2 — Concurrency and sessions (behavior under load)

Facts, verified in the v0.22.5 source; re-check them on the deployed version:
- Each turn runs on its own thread. There is no queue across sessions.
- `max_concurrent_sessions` rejects over-cap turns; it does not queue them.
- A DM = its own session. A channel = one shared session (because `group_sessions_per_user: false`
  and `MATTERMOST_REPLY_MODE` defaults to `off`). A thread = its own session.

| # | Change | Why |
|---|---|---|
| 2.1 | `display.busy_input_mode: queue` | Default `interrupt`: a second message in the same session redirects the running investigation. `queue` finishes it first |
| 2.2 | `cron.max_parallel_jobs: 1` (or 2) | Cron jobs stop competing with people for the LLM |
| 2.3 | Leave `max_concurrent_sessions` unset | A cap would reject people. Throttle at the LLM server instead |
| 2.4 | Ask the owner for the LLM server's parallel capacity (vLLM `max_num_seqs`), and record it | It is the real limit for all concurrent work |
| 2.5 | `MATTERMOST_REPLY_MODE`: RECOMMEND `thread` to the owner, do not apply it | It separates concurrent channel requests, but changes the shared channel context the owner wants to keep |

**Load test:** 8 DMs at once, plus one channel question, while the anomaly scan runs.
Record the time to first reply and to the final answer, and any 503s. Repeat after the changes.

## P3 — LLM resilience

| # | Check | Required state |
|---|---|---|
| 3.1 | Fallback | `fallback_providers` configured with a second endpoint (`guides/review/PERFORMANCE.md` §3.8). Test it: block the primary → the answer still arrives |
| 3.2 | Thinking | DeepSeek thinking on via the provider's `extra_body` / `chat_template_kwargs` as documented in PERFORMANCE.md. Confirm the endpoint honors it (compare reasoning tokens in Langfuse) |
| 3.3 | Timeouts | The provider request timeout and the gateway inactivity watchdog are set to values that fit a loaded server. Record the values |
| 3.4 | Cron on failure | Every cron job has `--failure-deliver` to the team home channel, so a silent failure is impossible |

## P4 — Cron jobs and pollers: correctness

For EACH job (anomaly scan, summary, Grafana poll, Jira poll):

| # | Required state |
|---|---|
| 4.1 | Gate script: quiet path prints `{"wakeAgent": false}` (empty stdout WAKES the model). See `guides/WAKE-AGENT.md` |
| 4.2 | Idempotent: a seen-set or watermark in `HERMES_HOME/data/noc/` is written ATOMICALLY (temp file + rename) and only after successful handling. A rerun or restart never re-posts the same alert/ticket |
| 4.3 | Bounded work per run (`per_run`), so one burst cannot flood the LLM |
| 4.4 | Error gate: a broken data source posts ONE error, then stays quiet until recovery (`noclib.error_gate` / `clear_error`) |
| 4.5 | The job's own runtime < its interval (5-min scan finishes < 5 min) at peak; measured |

Postgres is NOT needed for this. Add it only if file-based state proves insufficient, and then only one
`processed_events(source, key UNIQUE, handled_at)` table.

## P5 — Security

| # | Required state |
|---|---|
| 5.1 | All data-source credentials are read-only (Prometheus, Grafana, ES/Loki, DB, Jira = comment/transition only behind the `NOC_JIRA_ALLOW_*` switches) |
| 5.2 | `approvals`: `mode: manual`, `cron_mode: deny`, `unattended_mode: deny`, deny list in place (config.yaml). Test: ask the bot to restart a service → refused |
| 5.3 | Only allowlisted users can talk to the bot (`MATTERMOST_ALLOWED_USERS` or the deployed equivalent). Test with a non-listed user |
| 5.4 | Customer DMs: persistent memory is shared across ALL sessions of the profile. Either set `memory.memory_enabled: false` for the profile that customers reach, or keep customers off it. OWNER DECISION — ask, then record |
| 5.5 | Langfuse capture = `sanitized`; no raw customer payloads in traces |
| 5.6 | MCP: tools the agent can call are read-only, or mutating ones are denied by approvals. List them in `PRODUCTION-STATUS.md` |

## P6 — Observability and alerting

| # | Required state |
|---|---|
| 6.1 | Alerts (Prometheus rules, `deploy/monitoring.yaml`): gateway down; Mattermost platform down (`hermes_platform_up{hermes_platform="mattermost"}`); cron heartbeat stale; LLM error rate; fallback in use |
| 6.2 | Dashboard imported (`deploy/grafana/hermes-noc-dashboard.json`), linked in the runbook |
| 6.3 | Langfuse: latency per turn, tokens per turn, failed turns, visible per source (chat / cron) |
| 6.4 | Weekly: open the 10 slowest turns in Langfuse; record the cause (LLM queue, tool, many rounds) |

## P7 — Answer quality gate

| # | Required state |
|---|---|
| 7.1 | `evals/` cases cover the real question types (hop/rule/server/onset, "I don't know", read-only refusal). ≥ 15 cases from real past incidents |
| 7.2 | Run evals before every config/skill/prompt change; a drop blocks the change |
| 7.3 | Every answer with a finding has evidence (query/graph/log). "No data" is stated, not guessed. Spot-check 10 real answers |
| 7.4 | Jira auto-close stays in shadow → comment → close rollout (`guides/review/JIRA-POLLER.md`); move a stage only with the owner's OK |

## P8 — Operations

| # | Required state |
|---|---|
| 8.1 | Runbook (`guides/review/RUNBOOK.md`) updated for the real environment: restart, drain, upgrade, rollback, restore, rotate tokens, "bot silent" triage |
| 8.2 | `deploy/e2e_check.py` (or its equivalent) runs after every deploy; all checks green before announcing |
| 8.3 | Named owner and on-call path for the bot itself |
| 8.4 | User guide published (`guides/review/USER-GUIDE.md`) + the capability document |

---

## Definition of done (production)

- P1–P6 all green in `PRODUCTION-STATUS.md`, each with how it was verified.
- Load test (P2) passed, numbers recorded.
- Evals pass; 10 real answers spot-checked.
- One restore from backup and one failover to the fallback LLM were actually performed.
- Open owner decisions listed: reply mode (2.5), customer memory (5.4), LLM capacity (2.4), Jira stage (7.4).

## What to report back

`PRODUCTION-STATUS.md` must hold:
- a table of items, each with: before, change, verify, result;
- the open decisions for the owner;
- risks that remain.

Keep it short. No new features in this task.
