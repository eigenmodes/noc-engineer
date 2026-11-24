# Grafana dashboard and alerts for the agent

Hermes does not ship a Grafana dashboard. `deploy/grafana/hermes-noc-dashboard.json` is built for the
metrics Hermes v0.22.5 exports (`agent/monitoring/gateway_health_export.py`, `_OBSERVABLE_METRIC_NAMES`);
a test checks that every metric in the dashboard and in `deploy/monitoring.yaml` exists there.

## Path
`config.yaml monitoring:` → OTLP → OpenTelemetry Collector → Prometheus (or Mimir/Thanos) → Grafana.
OTel names become Prometheus names with `_` instead of `.`: `hermes.gateway.up` → `hermes_gateway_up`;
attributes become labels: `hermes.platform` → `hermes_platform`.
**Verify** after the first export: some collector/Prometheus setups add unit suffixes; if a panel is
empty, look up the real name in Prometheus (`{__name__=~"hermes_.*"}`) and adjust.

## Import
Grafana → Dashboards → New → Import → upload `deploy/grafana/hermes-noc-dashboard.json` → pick the
Prometheus data source. Variables: `namespace` (pod panels), `vllm_job` (model panels). Edit the
Langfuse link in dashboard settings.

## Panels
| Row | Shows | Source |
|---|---|---|
| Agent | gateway up, Mattermost up/degraded with error code, busy, active agents, restart requested, state | Hermes OTLP |
| Cron | heartbeat age, last success age, overdue, store writable, enabled/running jobs, skipped runs, catch-up | Hermes OTLP |
| Pod | restarts, memory, CPU of container `hermes` | kube-state-metrics, cAdvisor (if scraped) |
| Model endpoint | requests running/waiting, tokens/s, latency p50/p95 | vLLM `/metrics` (only if Kimi is served by vLLM and scraped) |

Not in Prometheus: per-turn detail and token cost per job (Langfuse), cron run spans
(`hermes.cron_execution`, a trace backend such as Tempo if the collector forwards traces).

## Alerts
`deploy/monitoring.yaml` (PrometheusRule): gateway down/absent, Mattermost disconnected
(`hermes_platform`), cron stalled (heartbeat > 600 s), jobs overdue, no successful run for 30 min.
They must live outside Hermes: a dead gateway cannot report itself.
