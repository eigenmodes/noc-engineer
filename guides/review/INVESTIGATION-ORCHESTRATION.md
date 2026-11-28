# Investigation Orchestration — implementation guide (for the implementing LLM)

Goal: a production investigation pipeline around the existing Hermes deployment.
Durable queue in PostgreSQL, max N concurrent investigations, isolated execution,
evidence-backed structured results, idempotent Mattermost notifications.

Read this whole file before writing code. It replaces the long spec: it keeps its
requirements, fixes its gaps, and records facts already verified in Hermes source.

---

## 0. Rules (non-negotiable)

1. Inspect before coding (§1). Never invent Hermes flags, config keys or APIs.
   Every Hermes fact below cites its source file; re-verify it on the DEPLOYED version.
2. Do not change `group_sessions_per_user: false`.
3. An investigation never runs inside a Mattermost conversation session.
4. No in-memory queues. PostgreSQL is the source of truth for business state.
   Hermes `state.db` stays Hermes-owned; never write business data there.
5. Authorization is enforced in code (worker, MCP server, DB layer), never by prompt.
6. No destructive action runs automatically. Investigations are read-only.
7. Never mix tenant data. Every query on tenant data takes a tenant scope argument.
8. COMPLETED only after the result is committed. Notify only from a committed outbox row.
9. Ship in phases (§10). Each phase ends with passing tests and a short report.
   Do not start the next phase without the owner's OK.

---

## 1. Stage A — inspection (produce `docs/orchestration/ASSESSMENT.md`)

Run and record the output of each:

| Check | How |
|---|---|
| Deployed Hermes version | `hermes --version` in the running container; image tag in k8s |
| Session mapping | read `gateway/session.py::build_session_key` and the Mattermost adapter (`plugins/platforms/mattermost/adapter.py`, `_handle_ws_event`) |
| Reply mode in prod | value of `MATTERMOST_REPLY_MODE` (default `off`) |
| Busy policy | `display.busy_input_mode` in prod config (default `interrupt`) |
| Oneshot flags | `hermes --help`, `hermes chat --help`: confirm `-z/--oneshot`, `-t/--toolsets`, `-s/--skills`, `--usage-file`, `-p/--profile` |
| Profiles | can a second profile run beside the gateway profile on the same host? |
| Memory toggle | `memory.memory_enabled`, `memory.user_profile_enabled` exist in deployed config defaults |
| API server option | is `gateway/platforms/api_server.py` present, with `/v1/runs`? (optional path, §3.2) |
| MCP server | list tools, their input/output schemas, which are read-only, how auth works, who owns the code |
| Existing code | `scripts/*.py`, `noclib`, `noc.py`, the Jira poller guide (`guides/review/JIRA-POLLER.md`), tests, Dockerfile, k8s |
| DB | is PostgreSQL available? Are SQLAlchemy/Alembic already dependencies? |

End the assessment with a list of gaps and any fact below that differs in the deployed version.

---

## 2. Verified Hermes facts (v0.22.5 source, `guides/hermes-agent`)

Re-verify each one on the deployed version.

**Sessions** (`gateway/session.py::build_session_key`)
- Key layout: `<ns>:<platform>:<chat_type>[:<chat_id>][:<thread_id>][:<user>]`.
- DMs are isolated per `chat_id`. One DM channel = one session per user↔bot pair.
- In channels, the user id is added only when `group_sessions_per_user` is true and the message is not in a thread.
  With our `false`, one channel = one shared session. Each thread = its own session.
- The Mattermost adapter maps `root_id` → `thread_id`. With `MATTERMOST_REPLY_MODE=thread`, a top-level
  channel post becomes its own thread root, and so its own session (`adapter.py` ~line 571). The default is `off`.
- The session key does not include the bot username or token.

**Concurrency**
- Every gateway turn runs on its own thread. There is no cross-session queue.
- `max_concurrent_sessions` (top level, default unset) REJECTS over-cap turns with a message; it does not queue.
  Do not use it as the investigation limiter.
- `display.busy_input_mode`: `interrupt` (default) | `queue` | `steer`. Applies to messages that arrive while the same session is busy.
- `cron.max_parallel_jobs` (default unset = unbounded; env `HERMES_CRON_MAX_PARALLEL`).
- `delegation.max_concurrent_children` (default 10).
- The Mattermost adapter ignores only the bot's own posts. Other bots' posts are processed.

**Oneshot execution** (`hermes_cli/oneshot.py`, `hermes_cli/_parser.py`)
- `hermes -z "<prompt>"` runs one turn, prints only the final content, and exits.
  Flags: `-m/--model`, `--provider`, `-t/--toolsets`, `-s/--skills`, `--usage-file`, `--reasoning`, `-r/--resume`.
  `-p/--profile` is accepted before argparse.
- ⚠ Oneshot loads rules, memory and AGENTS.md like a normal chat turn, AND auto-bypasses approvals (`HERMES_YOLO_MODE=1`).
  So the toolset passed with `-t` IS the permission boundary on the Hermes side. Never give a worker run a terminal,
  file-write or any mutating toolset. Real enforcement must still sit in the MCP server (§7).

**Memory**
- `memory.memory_enabled` and `memory.user_profile_enabled` (`hermes_cli/config_defaults.py`).
- Persistent memory is per profile and shared by all sessions of that profile. This is the tenant-leak risk (§6).

**Cron gate**
- A cron script that prints `{"wakeAgent": false}` does not wake the model. Empty stdout DOES wake it.

---

## 3. Architecture decisions

### 3.1 Execution: external worker plus a dedicated `investigator` profile (chosen)

```
producers ──► PostgreSQL (intake → correlate → queue)
                     │  claim (SKIP LOCKED, lease)
              worker pool (this repo, Python)
                     │  subprocess per investigation, with timeout:
                     │  hermes -p investigator -z "<prompt>" -t <allowlist> --usage-file <f>
                     ▼
              result JSON → validate (Pydantic) → commit result + outbox in one transaction
                     ▼
              notifier ──► Mattermost REST (bot token, channel + root_id)
```

- **Profile `investigator`:** its own HERMES_HOME, so its own `state.db`. Set `memory.memory_enabled: false`
  and `user_profile_enabled: false`. No messaging platforms. Same model and fallback config as the gateway.
  This isolates context and memory from the conversational gateway, and from other tenants.
  Before relying on a second profile on the same host, verify it is supported (§1).
- **Why not run investigations inside the gateway:** the conversation session would be polluted, and nothing
  in Hermes gives a durable queue.
- **Why not Hermes delegation for this:** delegations are children of a live parent turn. They are not durable
  and do not survive a restart.
- The worker passes ONLY the investigation input (tenant-scoped) in the prompt, and requires a JSON answer
  matching §5. On invalid JSON: one repair retry with the validation error, then FAILED(`invalid_output`).

### 3.2 Alternative (evaluate only, do not build first)
If `/v1/runs` on the API server exists in the deployed version, a worker could submit runs over HTTP
(it has `max_concurrent_runs` and run idempotency modules). Document whether it supports per-run toolsets and
profile isolation. Switch only if it is clearly better than the subprocess.

### 3.3 Persistence
Use what the project already has. If SQLAlchemy/Alembic are not present, use **psycopg 3** with plain numbered
SQL migrations (`migrations/0001_init.sql`, …) and a `schema_migrations` table, applied by `noc.py db-migrate`.
The reason: few dependencies, SQL that is easy to review, and `FOR UPDATE SKIP LOCKED` used directly.

### 3.4 Concurrency limit
`NOC_INV_MAX_ACTIVE` (default **3**, hard max 5). The LLM server is the real bottleneck, and chat turns use it too.
Raise the value only after measuring the LLM's capacity (vLLM `max_num_seqs`). Ask the owner for that number.

---

## 4. Lifecycle

States: `RECEIVED, ACCEPTED, CORRELATING, ATTACHED, QUEUED, RUNNING, RETRY_WAIT, COMPLETED, REVIEWED, NOTIFIED,
FAILED, TIMED_OUT, CANCELLED`.

Allowed transitions. Enforce them in the DB with a transition function plus a check, and reject anything else:

```
RECEIVED    → ACCEPTED | CANCELLED
ACCEPTED    → CORRELATING | CANCELLED
CORRELATING → ATTACHED | QUEUED
QUEUED      → RUNNING | CANCELLED
RUNNING     → COMPLETED | FAILED | TIMED_OUT | RETRY_WAIT | CANCELLED
RETRY_WAIT  → QUEUED | CANCELLED            (after backoff)
TIMED_OUT   → RETRY_WAIT | FAILED
COMPLETED   → REVIEWED | FAILED             (FAILED if validation rejects)
REVIEWED    → NOTIFIED
ATTACHED, NOTIFIED, FAILED, CANCELLED: terminal (FAILED also notifies, once, via the outbox)
```

- **REVIEWED** = automatic validation gate, not a person: the schema is valid, every `verified` finding has ≥1
  evidence reference, and there is no cross-tenant identifier in the output. A human review flag can be added
  later for customer-facing replies.
- Every transition appends a row to `investigation_events` (audit trail).
- **Retry:** max 3 attempts, backoff `min(2^n * 30s, 15m)` ± 20% jitter. Only transient errors retry
  (LLM 5xx or timeout, MCP timeout). Validation or permission errors fail immediately.
- **Timeout:** `time_budget_s` per investigation (default 600). The worker kills the subprocess → TIMED_OUT.
- **Cancel:** sets `cancel_requested`. The worker checks it between steps and on each heartbeat, then kills the subprocess.
- **Stale:** a RUNNING row whose lease has expired → back to QUEUED (attempt counted) by the reaper.

---

## 5. Data model (migration 0001)

UUID primary keys, `created_at`/`updated_at` everywhere, `tenant_id` NOT NULL where the data is tenant data.

- `tenants(id, slug UNIQUE, name)`
- `conversations(id, platform, channel_id, root_id NULL, tenant_id NULL, UNIQUE(platform, channel_id, root_id))`
- `global_incidents(id, correlation_key UNIQUE, kind, status, opened_at, closed_at, sanitized_summary TEXT)`
- `tenant_incidents(id, tenant_id, global_incident_id NULL, correlation_key, status, UNIQUE(tenant_id, correlation_key))`
- `investigations(id, public_id 'INV-…' UNIQUE, tenant_incident_id, tenant_id NULL, scope CHECK IN('tenant','global'),
  conversation_id NULL, source CHECK IN('chat','grafana','jira','anomaly'), idempotency_key UNIQUE,
  state CHECK(...), attempt INT, max_attempts INT, time_budget_s INT, tool_allowlist TEXT[],
  input JSONB, result JSONB, error JSONB, lease_owner, lease_until, heartbeat_at, next_attempt_at,
  cancel_requested BOOL, started_at, finished_at)`
  CHECK: `scope='tenant'` ⇒ `tenant_id IS NOT NULL`.
  Index: `(state, next_attempt_at)` for claiming.
- `investigation_events(id, investigation_id, from_state, to_state, actor, detail JSONB, at)`
- `findings(id, investigation_id, tenant_id NULL, kind CHECK IN('fact','hypothesis','recommendation'),
  text, confidence NUMERIC, shareable_global BOOL DEFAULT false)`
- `investigation_evidence(id, investigation_id, tenant_id NULL, type, ref, query, time_range, access_scope, digest)`
- `action_audit(id, investigation_id NULL, actor, tool, args_redacted JSONB, allowed BOOL, reason, at)`
- `notification_outbox(id, investigation_id, channel_id, root_id, payload JSONB, dedupe_key UNIQUE,
  state CHECK IN('pending','sent','failed'), attempts, sent_at, last_error)`

Idempotency keys: chat = Mattermost `post_id`; Grafana = alert fingerprint + startsAt; Jira = issue key + updated.
Retention: events/audit 180 days, outbox sent rows 30 days, results kept. Cleanup runs as `noc.py db-cleanup` from cron.

**Claim query (the core):**
```sql
WITH c AS (
  SELECT id FROM investigations
  WHERE state = 'QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at <= now())
    AND (SELECT count(*) FROM investigations WHERE state = 'RUNNING') < :max_active
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE investigations i SET state='RUNNING', lease_owner=:worker, lease_until=now()+:lease,
  heartbeat_at=now(), attempt=attempt+1, started_at=coalesce(started_at, now())
FROM c WHERE i.id = c.id RETURNING i.*;
```
The RUNNING count is racy under SKIP LOCKED. Serialize claims with `pg_advisory_xact_lock(<const>)` in the
same transaction, so the global cap holds exactly.

---

## 6. Correlation and tenant isolation

- **Correlation is deterministic code, run before queueing.**
  `correlation_key = scope|signal|target|time_bucket` (target = hop/server/rule/cluster; bucket = 15 min,
  configurable). Rules live in `noc.yaml correlation:`.
  - A matching open global incident → link the tenant incident, investigation → ATTACHED (no new run).
  - A matching tenant incident for the same tenant → ATTACHED to its running or most recent investigation.
  - No match → new incident, investigation → QUEUED.
  - The LLM never decides correlation.
- **Isolation, enforced in code:**
  - The DB layer: every tenant read takes `tenant_id` and filters on it. Add Postgres RLS if the team agrees.
  - The worker builds the prompt only from that tenant's rows, plus `global_incidents.sanitized_summary`.
    Another tenant's raw data never enters it.
  - Global findings reach tenants only through `findings.shareable_global=true` plus a sanitized text.
  - The `investigator` profile has memory disabled, so nothing carries over between runs.
  - The conversational gateway profile still has shared memory. Customer DMs must not store customer facts:
    either disable memory on that profile, or keep customers off it (owner decision, record it).

---

## 7. MCP and tools

- Inventory the existing MCP tools (§1). Reuse them; do not duplicate.
- Classify each tool as read-only or mutating, in `docs/orchestration/TOOLS.md`.
- The worker passes a per-investigation-type allowlist via `-t`. Because oneshot bypasses approvals, the allowlist
  contains read-only tools only.
- Enforcement in the MCP server, needed for production. If you do not own it, write the requirements and give them to its owner:
  read-only credentials for the investigator identity, mutating tools rejected for that identity, per-tool timeout,
  input validation, output size cap, structured errors, rate limit, audit log, secret redaction.
- Until the MCP server enforces this, record it as an open risk in the final report.

---

## 8. Result schema (Pydantic, `noc/investigation/models.py`)

```
InvestigationResult:
  investigation_id, incident_id, scope, tenant_id | None
  summary: str (≤ 600 chars, Hebrew for users)
  facts: [Finding]            # observed, each with evidence_refs ≥ 1
  hypotheses: [Finding]       # root-cause candidates, each with confidence 0–1 and evidence_refs
  recommendations: [str]
  evidence: [Evidence{type, ref, query, time_range}]
  customer_impact: str | None
  actions_executed: [str]     # must be empty for read-only runs; else FAILED
  limitations: [str]
  started_at, finished_at
```
A hypothesis is never shown as the root cause. The user-facing text labels the parts:
"נצפה" (observed), "השערה" (hypothesis), "המלצה" (recommendation).

---

## 9. Intake and notification

- **Alerts / Jira / anomaly:** the existing pollers (`scripts/grafana_poll.py`, `scripts/jira_poll.py`,
  `scripts/anomaly_scan.py`) INSERT into intake with an idempotency key, instead of waking the agent with the work.
  They print `{"wakeAgent": false}`.
- **Chat:** the conversational agent calls a read/write-to-own-DB command, `noc.py inv-create`
  (or an MCP tool, if one exists), with the summary, the tenant and the origin channel/root. It replies with an ack:
  "פתחתי חקירה INV-123, אעדכן כאן". Then the conversation continues normally.
  OPEN QUESTION, verify first: can a tool call obtain the originating channel id and post id? If not, use one of these
  and document which:
  (a) a Mattermost slash command or outgoing webhook to an intake HTTP endpoint;
  (b) the user mentions the bot in a thread and the intake reads the thread via the Mattermost API.
- **Follow-ups:** the conversational agent reads results with `noc.py inv-get INV-123`. That command checks that
  the caller's channel is allowed to see the investigation's tenant. The result is never injected into the chat session.
- **Notifier:** a loop that sends `notification_outbox` rows in `pending` state via the Mattermost REST API
  (`POST /api/v4/posts` with `channel_id`, `root_id`), marks them `sent`, and retries with backoff.
  `dedupe_key` = `investigation_id:kind` → at most one final message per investigation.
- **Progress:** one message on start if the investigation was QUEUED for more than 60s. No per-tool updates.

---

## 10. Phases (each one ends with passing tests, a short report, and the owner's OK)

| Phase | Scope | Done when |
|---|---|---|
| 1 | Assessment (§1) + design doc with diagrams (state machine, sequences: request, run, recovery, notify) | Owner approves |
| 2 | Migrations, DB layer, state machine, claim/lease/heartbeat/reaper, retries, cancel, timeout | Concurrency + recovery tests pass |
| 3 | Worker + `investigator` profile + oneshot integration + result validation | 1 real read-only investigation end to end |
| 4 | Outbox + notifier + `inv-create` / `inv-get` + pollers as producers | Duplicate and notification-idempotency tests pass |
| 5 | Correlation rules + tenant isolation tests | Isolation tests pass |
| 6 | Metrics, logs, dashboard, runbook, k8s manifests, backup | E2E check extended (`deploy/e2e_check.py`) |
| 7 | MCP hardening (with the MCP owner) | Authorization tests pass |

**Rollout:** shadow mode first. Investigations run and results are stored, but the notifier posts only to a private
test channel. Then team channel. Then customers.

---

## 11. Tests (minimum)

Unit: transitions (valid and invalid), backoff, correlation keys, result validation.
Integration on a real Postgres (testcontainers or the compose service):
- 20 workers × 50 jobs → never more than `max_active` RUNNING, no double claim.
- Same idempotency key twice → one investigation.
- A worker killed mid-run → the lease expires → reclaimed. The result is written exactly once.
- Timeout → TIMED_OUT → retry → FAILED after max attempts.
- Cancel while QUEUED and while RUNNING.
- Notifier crash after the send, before marking → no duplicate post (dedupe_key plus a check of the post by props).
- Tenant A's run never reads tenant B's rows. Output containing a B identifier is rejected at REVIEWED.
- Fake `hermes` binary (a script) for deterministic worker tests, plus one marked live test.

---

## 12. Observability

Prometheus (worker `/metrics`): `noc_inv_queue_depth`, `noc_inv_active`, `noc_inv_duration_seconds` (histogram),
`noc_inv_total{state}`, `noc_inv_retries_total`, `noc_inv_stale_leases_total`, `noc_notify_failures_total`,
`noc_inv_by_tenant_total{tenant}`, `noc_tool_latency_seconds{tool}` (from the usage file or logs).
JSON logs with `investigation_id, incident_id, tenant_id, conversation_id, worker_id`. No secrets, no raw customer payloads.
Add panels to `deploy/grafana/hermes-noc-dashboard.json`.

---

## 13. Hermes config changes — owner decisions, do NOT apply silently

| Change | Why | Effect on today's behavior |
|---|---|---|
| `display.busy_input_mode: queue` | Follow-ups wait instead of interrupting | A follow-up no longer redirects a running answer |
| `cron.max_parallel_jobs: 1` | Scans stop competing with people for the LLM | Cron jobs run one at a time |
| `MATTERMOST_REPLY_MODE=thread` | Each channel request gets its own session | Changes the shared channel context; the owner wants that preserved. Recommend only, do not apply |
| `investigator` profile | Isolation (§3.1) | None on the gateway |

---

## 14. Ask the owner before Phase 2

1. Deployed Hermes version and image tag.
2. PostgreSQL instance and credentials path (secret name).
3. LLM capacity (parallel requests) → `NOC_INV_MAX_ACTIVE`.
4. MCP server: repo, owner, auth model.
5. Tenant list and how a Mattermost channel or user maps to a tenant.
6. Whether customers talk to the bot in DMs today (memory policy, §6).

## 15. Final deliverables

Assessment, compatibility report, design doc with diagrams, migrations, DB layer, queue + worker, notifier,
`noc.py inv-*` commands, tests, k8s and compose files, runbook (start, stop, drain, replay a failed run, restore backup),
security review, and an explicit list of unresolved risks. Known risk to list from day one: oneshot bypasses approvals,
so tool restriction depends on `-t` and on the MCP server.
