# Performance: keep thinking, cut the waiting

Goal: answers that use reasoning (DeepSeek V4 thinking) but arrive fast, on a shared, busy model
endpoint. Settings verified in Hermes v0.22.5 source/docs unless marked **verify**.

## 1. The one rule
**Waiting time ≈ number of model rounds × (queue time + thinking time per round).**
Every tool call sends the conversation back to the model, which thinks again. A question answered in
7 rounds thinks 7 times. Tools themselves (Prometheus, ECK) take seconds; model rounds take tens of
seconds each on a loaded endpoint. So:
- **fewer rounds** is the biggest lever;
- **less load on the endpoint** shortens the queue for every round;
- thinking per round matters less than the number of rounds.

Hermes already runs several tool calls from one model reply before going back to the model (read-only
tools in parallel, terminal commands one after another). Slow agents are the ones whose model asks for
one tool, looks, asks for the next.

## 2. Measure before changing (Langfuse)
| Metric | Where | Target for a chat investigation |
|---|---|---|
| model rounds per question | generations per trace | ≤ 3 |
| tool calls per round | tool spans between generations | > 1 when several sources are needed |
| seconds per round | generation latency | depends on endpoint; watch the trend |
| queue time | vLLM `time_to_first_token` (Grafana model row) | low and flat |
| prompt tokens per round | generation usage | stable, no growth across rounds |
| total time to answer | trace duration | the number users feel |

Run the same 5 questions before and after each change (`evals/run_evals.py` with `--only`).

## 3. What to do, in order of effect

### 3.1 One investigation command instead of many queries (biggest win)
Today, "hermeticity dropped on server 1":
```
think → load skill → think → prom: rule rate → think → prom: ingress → think → prom: kafka lag
→ think → eck errors → think → change log → think → answer            (7 rounds)
```
With `noc.py investigate`:
```
think → noc.py investigate --server srv1 --symptom hermeticity --since 2h
        (code, no model: per-hop now-vs-last-week, ECK errors around onset, changes in window)
→ think → answer with evidence                                          (2 rounds)
```
Contract of the command (compact output, not raw series):
```json
{"server": "srv1", "onset": "13:42",
 "hops": [{"hop": "ingress", "now_vs_week": 0.98, "status": "ok"},
          {"hop": "enrichment", "now_vs_week": 0.41, "status": "drop", "first": true},
          {"hop": "rules", "now_vs_week": 0.38, "status": "drop"}],
 "eck": {"errors_after_onset": 312, "top": "enrichment timeout to <service>"},
 "changes": [{"at": "13:40", "what": "rule config update #881"}],
 "not_checked": ["argo: no access"]}
```
Requirements: the hop list and per-hop PromQL in `noc.yaml` (`ENVIRONMENT-KNOWLEDGE.md`); every
number traceable to a query (the command returns the query with each value on request, `--evidence`).
Cap output (top N errors, no full series) so the next round reads little.

### 3.2 Tell the model how to work (SOUL.md / skill)
- "For an investigation, run `noc.py investigate` first. Run extra queries only if its result is
  ambiguous, and request all of them in one reply."
- "Plan which data you need before calling tools; batch independent calls in the same reply."
- Keep the core method in `SOUL.md` / one short skill: loading a skill is itself a round.

### 3.3 Thinking only where a person waits
| Work | Thinking | How |
|---|---|---|
| Chat investigations, customer questions | **on** (Think High) | main model config |
| Cron: anomaly scan, alert triage formatting, daily summary, ticket polling | **off** | per job: `hermes cron edit <id> --reasoning-effort none` (flag exists in v0.22.5) |
| Background: context compression, titles | **off** | `auxiliary.compression.reasoning_effort: none` (per-task key, v0.22.5) |
**Verify** on your serving stack that `reasoning_effort: none` actually turns thinking off (vLLM's
DeepSeek V4 template reads `chat_template_kwargs`). If not, define a second named provider without
thinking and point the cron jobs at it (`--provider`), see 3.7.

### 3.4 Stop waking the model for nothing
Cron scripts must print `{"wakeAgent": false}` when there is nothing new (`../WAKE-AGENT.md`). A scan
every 5 minutes that always wakes a thinking model is a permanent load on the same endpoint your chat
waits for.

### 3.5 Keep context small
Every round re-reads the whole conversation.
- `/new` in the channel when the conversation drifts; long shared channel sessions grow fastest.
- `compression.threshold` lower (default 0.50 of the context window; e.g. 0.35) if prompt tokens per
  round keep growing.
- Compact tool output (3.1); no raw JSON dumps; skills short, details in `references/` read on demand.

### 3.6 Make waiting understandable (Mattermost)
```yaml
streaming:
  enabled: true            # Mattermost supports message edits: text appears as it is written
display:
  platforms:
    mattermost:
      tool_progress: 'off'            # no tool bubbles with script paths
      interim_assistant_messages: false
      long_running_notifications: true  # one "working on it" during long silences
      live_status: verb
```

### 3.7 Endpoint side (ask the model-serving team)
| Ask | Why |
|---|---|
| Think **High**, not Max | Max produces far more reasoning tokens; on vLLM it also needs `--max-model-len` ≥ 393216 |
| Prefix caching on (`--enable-prefix-caching`) | system prompt, tool schemas and skills repeat every round; cached prefix = no re-processing |
| Speculative decoding (MTP / DSpark for V4) | more output tokens per second; reasoning is output tokens |
| Separate capacity or priority for interactive traffic | chat should not queue behind batch work |
| Expose vLLM `/metrics` to Prometheus | queue and token rate on the Grafana dashboard |
| How thinking is controlled (field, default) | so Hermes sends the right field (`extra_body` on a named provider) |

Named providers (thinking on for chat, off for batch), **verify** field names with the serving team:
```yaml
providers:
  deepseek-think:
    api: https://<endpoint>/v1
    key_env: OPENAI_API_KEY
    default_model: <model-id>
    extra_body: {chat_template_kwargs: {thinking: true, reasoning_effort: high}}
  deepseek-fast:
    api: https://<endpoint>/v1
    key_env: OPENAI_API_KEY
    default_model: <model-id>
    extra_body: {chat_template_kwargs: {thinking: false}}
model:
  provider: deepseek-think
```
Cron jobs: `hermes cron edit <id> --provider deepseek-fast`.

### 3.8 Failures: fallback to a second model
Official reference: `../HERMES-REFERENCE-v0.22.5.md`, section "Fallback Providers" (v0.22.5 docs).

**When it switches** (after retries are exhausted, unless noted): HTTP 429, **500/502/503**, invalid
or empty responses repeatedly; 401/403/404 immediately. Hermes keeps the conversation, swaps
model/provider/client in place and continues the same turn.
**Turn-scoped:** every new user message starts on the primary again; within one turn it switches at
most once (if the fallback also fails, normal retries and then an error).
**Reasoning is re-resolved** for the fallback model: its `agent.reasoning_overrides` entry, else the
global `agent.reasoning_effort`.
**Cost of a switch:** the fallback has no prompt cache for the conversation, so the first request
re-reads the whole history (and again when the primary comes back).

**Configuration (`config.yaml`, top level):**
```yaml
fallback_providers:                    # list, tried in order; each entry needs provider AND model
  - provider: custom                   # any OpenAI-compatible internal endpoint
    model: <backup-model-id>           # exactly as the endpoint lists it (GET /v1/models)
    base_url: http://<backup-endpoint>/v1
    key_env: BACKUP_LLM_KEY            # NAME of the env var holding the key (put the key in the Secret)

agent:
  api_max_retries: 1                   # with a fallback: fail over fast instead of retrying the dead primary
  reasoning_overrides:                 # optional: thinking level per model (bare model id matches fallback entries)
    "<backup-model-id>": low           # e.g. a small backup model without heavy thinking
```
Legacy `fallback_model:` (singular) is still read; `fallback_providers` wins when both exist.
Optional: `fallback.min_switch_reset_seconds` (default 0) skips switching on a rate limit whose
declared reset is sooner than that.

**Choosing the backup model**
- **Internal only.** An external provider would send customer data out of the network (`SECURITY.md`).
- **Must do tool calling.** Without it the backup answers from memory. Test it first: point
  `model:` at it in a test pod and run `e2e_check.py` (`model.tool_calling`).
- **Expect lower quality** than DeepSeek V4 with thinking; the goal is an answer instead of silence or
  an error. Run `evals/run_evals.py` against it once so the team knows what to expect.

**How to add or change it**
| Where | How | When it takes effect |
|---|---|---|
| This repo (recommended) | edit `fallback_providers` in `config.yaml`, add `BACKUP_LLM_KEY` to Secret `hermes-noc-env`, rebuild/redeploy | next pod start (`start.sh` replaces `config.yaml` on every start) |
| In the pod, interactive | `hermes fallback` (menu) or `hermes fallback add` / `list` / `remove` / `clear` | written to `config.yaml`, **but overwritten by the repo copy on the next restart**: copy the change into git |
| Change the backup model | change `model:` (and `base_url` if it moved) in the entry; same rollout as above | next start |
| Disable fallback | remove the list (or `hermes fallback clear`, then commit) | next start |

**Verify after a change**
1. `kubectl exec deploy/hermes-noc -- hermes fallback list` shows the entry.
2. In a test pod, make the primary fail (wrong `base_url`), ask a question in chat: the answer comes from
   the backup and the reply carries the fallback notice; the Langfuse trace shows the backup model.
3. Restore the primary; the next message goes to the primary again.

Without a second endpoint this section does not apply: Hermes retries the primary 3 times
(`agent.api_max_retries`), then waits 15/30/60/60/60 s (`agent.auto_recovery_cycles: 5`) with a visible
countdown, which is the long silence users see when the model is down.

## 4. Later, only if still slow
- **Two profiles / deployments:** `sentinel` (cron, no thinking) and `investigator` (chat, thinking)
  from the same repo. Complete isolation of load and context.
- **Parallel subagents (`delegate_task`)** per hop for very broad investigations. Helps only if the
  endpoint batches concurrent requests; adds rounds for the orchestrator. Try after 3.1.

## 5. What not to do
- Raise effort to Max "for quality" without evals proving it helps.
- Build swarms/Kanban teams before one agent is fast and correct.
- Add memory/graph tools for speed: they add rounds. Network knowledge goes into skills and `noc.yaml`.
- Lower thinking for chat before cutting rounds: rounds are the bigger cost.

## 6. Checklist
| # | Step | Owner | Done when |
|---|---|---|---|
| 1 | Baseline: rounds and seconds per question on 5 questions | team | numbers recorded |
| 2 | `wakeAgent` in every cron script | dev | quiet runs show `wakeAgent=false` |
| 3 | Cron + auxiliary without thinking | dev | Langfuse: cron generations have no reasoning |
| 4 | Hop table + PromQL filled | NOC team | `e2e_check.py config.anomaly_checks` PASS |
| 5 | `noc.py investigate` + SOUL/skill instruction | dev | ≤ 3 rounds on the 5 questions |
| 6 | Mattermost display + streaming | dev | no script paths in chat, text streams |
| 7 | Endpoint asks (3.7) | serving team | prefix cache on, High not Max, metrics in Grafana |
| 8 | Re-measure, run full evals | team | faster, pass rate not lower |
