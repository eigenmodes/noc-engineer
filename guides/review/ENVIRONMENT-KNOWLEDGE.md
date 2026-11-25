# Teaching the agent your environment

The agent is only as good as what it knows about your network. Today that knowledge is `TBD`. This
guide says what to collect, in which format, and where each piece goes. Only the NOC team can supply
the content; an LLM helping with this must never invent hosts, metrics or queries.

## Where knowledge lives
| Kind | Place | Why there |
|---|---|---|
| Endpoints, credentials | k8s Secret `hermes-noc-env` | never in git |
| Queries the scripts run (anomaly checks, customer JQL, index) | `skills/noc-tools/assets/noc.yaml` | read by code, validated by tests and `e2e_check.py` |
| Hop list | `noc.yaml` `pipeline.hops` | investigations are checked against it (`investigation.validate`) |
| How the network works: hops, metric per hop, healthy ranges, failure patterns | `skills/noc-environment/SKILL.md` + `skills/noc-environment/references/*.md` | loaded for every investigation; versioned in git |
| Things the agent learns while working | `MEMORY.md` (agent-written, 2,200 chars) | not a place for your reference data |

Do not put reference data in `SOUL.md` (identity only) or in `MEMORY.md` (small, agent-owned).

## 1. The data path (hops)
Fill one row per hop, in path order. The hop id is what the agent writes in findings and what evals
compare against.

| hop id | what it is | where it runs | metric that shows it is healthy (PromQL) | healthy range | logs (ECK index/query) | owner |
|---|---|---|---|---|---|---|
| `ingress` | traffic into the servers | capture servers | `sum by (instance) (rate(<rx metric>[5m]))` | vs last week ±50% | | |
| `capture` | capture application | servers | | | | |
| `kafka` | transport | Kafka cluster | consumer lag per group | lag < N min | | |
| `processing` | k8s processing (Argo deployed) | Rancher/OpenShift | | | | |
| `enrichment` | internal enrichment | | | | | |
| `rules` | rule matching | rule & config system | `sum by (rule_id) (rate(<rule match metric>[5m]))` | | | |
| `storage` | Postgres / ECK | | | | | |

Then:
- `noc.yaml` → `pipeline.hops: [ingress, capture, kafka, processing, enrichment, rules, storage]` (your ids).
- `skills/noc-environment/SKILL.md` → replace the `## Environment knowledge` TBD with this table.

## 2. Anomaly checks (the 5-minute scan)
Each check is an instant vector with **one series per entity** (server, port, rule). The scan compares
it with the same moment last week.
```yaml
anomaly:
  baseline: -7d
  cooldown_minutes: 60
  checks:
    - name: port_in_rate                       # stable id, appears in findings
      query: sum by (instance) (rate(<rx bytes metric>[5m]))
      min_ratio: 0.5                           # now/last-week below this = drop
      max_ratio: 2.0                           # above this = spike
      min_baseline: 1000                       # ignore entities that were near zero last week
```
Start with the three in `noc.yaml` (port in, port out, rule rate). Test each query in Grafana first:
it must return one series per entity, and the numbers must look right for a normal hour.
Tune ratios after a week of findings: too many findings → widen; missed incidents → narrow.

## 3. Failure patterns (the most valuable part)
One file: `skills/noc-environment/references/failure-patterns.md`. One block per pattern you have
seen more than once:
```markdown
## Rule hermeticity drops after a rule/config change
- Symptom: rule_rate for one rule drops > 50% vs last week; customer reports missing matches.
- First hop to check: rules. Then enrichment (coupling) if several rules drop together.
- Evidence: rule change log at the onset (who/what changed), rule_rate per rule_id around onset.
- Not this if: ingress for the same servers also dropped → start at ingress.
- Usually resolved by: <team / action>.
```
Cover at least: hermeticity, coupling (enrichment), configuration update, maintenance/upgrade,
packet loss, traffic load. Add a line to `SKILL.md`: "Before concluding, read
`references/failure-patterns.md` and say which pattern fits or that none does."

## 4. "What changed" sources
The method's step 2 asks what changed around the onset. Tell the agent where it can look, and only
list sources it can actually query:
| Source | How the agent reads it | Status |
|---|---|---|
| Deployments (Argo CD) | | TBD: needs read access or a metric/log |
| Rule / configuration changes | | TBD |
| Maintenance calendar | Jira project/JQL? | TBD |
If a source has no tool yet, write that in `SKILL.md` ("not available: ask the team") instead of
letting the agent guess.

## 5. Customers ↔ servers ↔ rules
For customer tickets and DMs the agent must map a customer to their servers and rules. Write where that
mapping lives (Jira field, label, CMDB, config system) and how to query it. Without it the agent
cannot scope a customer question; it must say so.

## 6. Glossary
Terms the team uses (Hebrew and English) so the agent understands questions:
`הרמטיות` = rule hermeticity, `צימוד` = rule coupling (enrichment), `איבודים` = packet loss, ...
Add to `skills/noc-environment/SKILL.md` under `## Glossary`.

## 7. Verify
1. `python3 -m pytest -q tests` (config schema, hop list).
2. In the pod: `python3 /opt/noc-engineer/e2e_check.py` → `config.anomaly_checks`, `backend.*` PASS.
3. Ask in Mattermost about a known recent event; open the trace in Langfuse: right queries, right hop.
4. Add the event to `evals/cases.yaml` and run `EVALS.md`.
