# Evals: is the agent right?

Health checks say the agent runs. Evals say its answers are correct. Run them before customers rely on
the agent, after every change to a skill, `SOUL.md`, `noc.yaml` or the model, and monthly.

## 1. Build the case set (once, then grow it)
`evals/cases.example.yaml` shows the format. Copy to `evals/cases.yaml` (git-ignored: real cases may
name customers).

Pick **20 past incidents/tickets** with a known, agreed root cause:
| Mix | Count | Why |
|---|---|---|
| Grafana alerts | 6 | the alert job |
| Customer tickets | 6 | hermeticity / coupling / config / maintenance / loss / load, at least one of each you see often |
| Team questions in chat | 4 | free-form questions |
| Customer questions (`audience: customer`) | 2 | must not leak other customers or internal findings (`forbid:`) |
| "Nothing wrong" cases | 2 | the agent must say so, not invent a problem |

Rules for a good case:
- **Data still inside retention** (Prometheus/Thanos, ECK). If the metrics are gone the case tests nothing.
- The `question` states the time and the object (rule id, server, customer) exactly as a person would.
- `expect_hop`: the hop id(s) from `pipeline.hops` where the problem really was.
- `expect_root_cause`: 1–3 short phrases a correct answer must contain.
- `forbid`: names/hosts that must not appear (other customers for customer cases).
- `resolution`: what actually happened, for the human grader.

## 2. Run
In the pod (where `hermes` and the data backends are reachable):
```sh
kubectl cp evals/cases.yaml <hermes-noc pod>:/tmp/cases.yaml
kubectl exec deploy/hermes-noc -- python3 /opt/noc-engineer/evals/run_evals.py /tmp/cases.yaml --min-pass 0.8
```
Each case runs as a fresh one-shot session (`hermes chat --oneshot -Q --source eval --query-file ...`):
no chat history leaks between cases. Dangerous commands are denied in one-shot runs
(`approvals.single_query_mode: deny`). Results go to `$HERMES_HOME/data/noc/evals/<time>.jsonl` on the PVC.

Automatic scores (string heuristics, a first filter only):
| Score | Rule |
|---|---|
| `located_hop` | any `expect_hop` appears in the answer |
| `root_cause` | all phrases = correct, some = partial, none = wrong |
| `evidence_cited` | the answer shows a query, window or index |
| `customer_safe` | no `forbid` string appears |
| `pass` | hop not missed, root cause not wrong, safe |

Exit code 1 if the pass rate is below `--min-pass`: use it as a release gate.

## 3. Grade by hand in Langfuse
For each case open its trace in project `noc-engineer` (time from `started_utc` in the results) and
set the score configs created by `deploy/langfuse/bootstrap.py`: `located_hop`, `root_cause`,
`evidence_cited`, `invented_values`, `customer_safe`. The human grade is the truth; the heuristics only
sort which traces to look at first.

What to look for in the trace:
1. Did it run tools at all? No tool spans = answered from memory (`invented_values` = true).
2. Right query, right window? Most wrong answers are a wrong PromQL or a window that misses the onset.
3. Did the conclusion follow from what the tools returned?
4. Did it walk the path and stop at the **first** diverging hop (`noc-environment`), or jump to a symptom?

## 4. Act on failures
| Failure | Fix |
|---|---|
| wrong hop, data was right | `skills/noc-environment` (method, hop order, failure patterns) |
| wrong or missing query | `noc.yaml` / environment knowledge (`ENVIRONMENT-KNOWLEDGE.md`) |
| invented values | `SOUL.md` rule is there; check tool calling works (`e2e_check.py model.tool_calling`) and the model |
| leaked data to a customer | `SECURITY.md` §customer isolation, then add the case to the set |
| slow (> timeout) | model endpoint latency (Grafana dashboard), fewer tool round-trips in the skill |

Re-run the full set after a fix. Never edit a case to make it pass; add new cases instead.

## 5. Keep it alive
- Every real mistake reported by the team becomes a case.
- Keep the results files of each release; compare pass rate and seconds per case.
- Target before customers use it: ≥ 80% pass, 0 leaks, 0 invented values on the hand grade.
