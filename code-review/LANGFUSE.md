# Langfuse for the NOC agent: deploy and connect, end to end

What it gives: every turn of the agent as one trace (model calls, tool calls with input/output, tokens,
latency, errors), cost per job, and scores to grade answers. Health and alerts stay in Grafana
(`deploy/monitoring.yaml`); Langfuse answers "why did it answer that".

Verified against: Hermes v0.22.5 source (`code-review/hermes-agent`), Langfuse Helm chart langfuse-k8s
2.2.6 (appVersion 4.83.0, its `examples/minimal-installation`), Langfuse docs for headless
initialization and the public API. Anything marked **verify** was not tested on a cluster.

```
Hermes pod ── langfuse plugin (hooks: turns, model requests, tool calls) ──HTTPS──▶ langfuse-web ──▶ langfuse-worker
                                                                                     │
                                                         Postgres · ClickHouse · Valkey · S3 (SeaweedFS)
```

## Files
| File | What |
|---|---|
| `deploy/langfuse/secret.example.yaml` | two Secrets: `langfuse` (app + datastores) and `langfuse-init` (org, project, API keys, first user) |
| `deploy/langfuse/values.yaml` | Helm values: secrets by reference, telemetry off, sign-up off, ingress, headless init on the web pod |
| `deploy/langfuse/install.sh` | prerequisites (cert-manager, ClickHouse operator) + `helm upgrade --install` |
| `deploy/langfuse/bootstrap.py` | idempotent project setup: model price for Kimi + 6 score configs |
| `deploy/Dockerfile`, `deploy/start.sh`, `deploy/k8s.yaml` | Hermes side: SDK in Hermes' Python, plugin install from an internal mirror, env |
| `deploy/e2e_check.py` | check `langfuse.tracing`: reachable, keys valid, plugin installed |

## 0. Requirements
- Kubernetes ≥ 1.28, Helm ≥ 3.17 (ClickHouse operator requirement), an ingress controller or an OpenShift Route.
- Storage class for the bundled datastores.
- **Air-gapped** network, mirror before you start:
  - charts: `oci://ghcr.io/langfuse/langfuse-k8s/charts/langfuse` 2.2.6, `oci://quay.io/jetstack/charts/cert-manager` v1.20.2,
    `oci://ghcr.io/clickhouse/clickhouse-operator-helm` 0.0.8, and the chart's dependencies (`helm dependency build` on a connected machine);
  - images: `helm template` the three charts with your values and mirror every `image:` (Langfuse web/worker
    from `docker.langfuse.com/langfuse/...`, `postgres`, `valkey/valkey`, `clickhouse/clickhouse-server`,
    `clickhouse/clickhouse-keeper`, SeaweedFS, cert-manager, operator); then set each `repository:` to your registry in `values.yaml`;
  - git: `NousResearch/hermes-official-plugins` (the `langfuse/` folder is the plugin);
  - PyPI: `langfuse`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` in your mirror.

## 1. Secrets
```sh
cd deploy/langfuse
cp secret.example.yaml secret.yaml       # secret.yaml is git-ignored
# fill every <...>: openssl rand -hex 32 (salt, encryption-key, sk), -base64 32 (nextauth), -hex 16 (passwords, pk)
```
`langfuse-init` creates on first start: org `noc`, project `noc-engineer` (30-day retention), the API key
pair, and the first user (Owner). Initialization does not change an existing user's password.
Keep `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `_SECRET_KEY`: Hermes uses them.

## 2. Install Langfuse
Edit `values.yaml`: `nextauth.url` and the ingress host (TBD), ingress class, image repositories if mirrored.
```sh
./install.sh            # NS=langfuse CHART_VERSION=2.2.6 by default; CHART=<mirror oci path> if air-gapped
```
OpenShift: set `langfuse.ingress.enabled: false` and expose `svc/langfuse-web` port 3000 with a Route
(TLS edge). **Verify** the bundled datastores run under your SCC; if not, point them at existing
Postgres / ClickHouse / Redis / S3 (`*.deploy: false`, see the chart's `examples/external-components`).
Check: open the URL, log in with the init user, project `noc-engineer` exists.

## 3. Project setup (models + scores)
```sh
LANGFUSE_URL=https://langfuse.<domain> LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-... \
  python3 deploy/langfuse/bootstrap.py --model kimi-k3 --input-price 0 --output-price 0
```
- `--model` = `model.default` in `config.yaml`, exactly as Hermes sends it. Prices are USD per token;
  0 counts tokens without cost. Set an internal cost (e.g. GPU cost / throughput) to see money per job.
- Score configs created: `located_hop`, `root_cause` (wrong/partial/correct), `evidence_cited`,
  `invented_values`, `customer_safe`, `user_feedback`. Use them to grade traces in the UI and in the
  20-incident quality run.
- Safe to re-run (`--dry-run` shows what it would do).

## 4. Connect Hermes
1. **Image** (`deploy/Dockerfile`): installs the SDK into the Python that runs `hermes` and fails the build
   if `import langfuse` fails. Air-gapped: `docker build --build-arg PIP_INDEX_URL=https://<mirror>/simple ...`.
2. **Secret `hermes-noc-env`**:
   ```
   HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...          # = LANGFUSE_INIT_PROJECT_PUBLIC_KEY
   HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
   HERMES_LANGFUSE_BASE_URL=https://langfuse.<domain>
   LANGFUSE_PLUGIN_SOURCE=https://<git>/<group>/hermes-official-plugins.git#langfuse   # air-gapped only
   ```
   `deploy/k8s.yaml` already sets `HERMES_LANGFUSE_CAPTURE=sanitized` (secrets redacted, fields truncated)
   and `HERMES_LANGFUSE_ENV=production`. Other knobs: `HERMES_LANGFUSE_SAMPLE_RATE` (0–1),
   `HERMES_LANGFUSE_MAX_CHARS` (default 12000), `HERMES_LANGFUSE_DEBUG=true` for the first run.
3. **Restart the pod.** `start.sh` installs the plugin once into `HERMES_HOME/plugins` (on the PVC) from
   `LANGFUSE_PLUGIN_SOURCE` (`#langfuse` = folder inside the repo; the bare name `langfuse` needs the public
   catalog), then enables it. The gateway loads plugins only at start.

Manual install, if start.sh reports `WARN: Langfuse plugin not installed`:
```sh
kubectl exec -it deploy/hermes-noc -- sh
hermes plugins install "https://<git>/<group>/hermes-official-plugins.git#langfuse" --yes-deps --enable
# private git: credential helper or ssh (git@host:group/repo.git#langfuse)
# last resort: copy the repo's langfuse/ folder to $HERMES_HOME/plugins/langfuse and `hermes plugins enable langfuse`
```

## 5. Verify end to end
1. `kubectl exec deploy/hermes-noc -- python3 /opt/noc-engineer/e2e_check.py` → `langfuse.tracing PASS`.
2. `hermes plugins list` shows `langfuse` enabled.
3. Ask the bot one question in Mattermost → a trace appears in project `noc-engineer` within a minute,
   with model generations (tokens filled) and tool spans (e.g. `noc.py metrics ...`).
4. Tokens empty? The model endpoint does not return `usage` (see "Troubleshooting").
5. Remove `HERMES_LANGFUSE_DEBUG` after the first good trace.

## 6. Using it
- **Wrong answer:** open its trace; check which query ran, on which window, what came back, then whether
  the model's conclusion follows. Grade with `located_hop`, `root_cause`, `invented_values`.
- **Cost:** filter by trace name / session; cron jobs should appear only when they found something (`WAKE-AGENT.md`).
- **Before/after a change** to a skill or `SOUL.md`: compare scores and latency on the same questions.
- **Privacy:** customer data stays in your cluster, 30-day retention, `sanitized` capture. For
  production at volume, `HERMES_LANGFUSE_SAMPLE_RATE=0.2` or capture `metadata` (no content).

## Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| `hermes plugins install langfuse` fails offline | bare name resolves through the public catalog | use `LANGFUSE_PLUGIN_SOURCE` with the internal git URL `...#langfuse` |
| install fails on dependencies | it tries PyPI | SDK is baked in the image; `--no-deps` then `hermes plugins enable langfuse` |
| `import langfuse` fails at build | system pip ≠ Hermes' Python, or no mirror | the Dockerfile uses Hermes' interpreter; pass `PIP_INDEX_URL` |
| plugin enabled, no traces | env not in the pod, wrong URL/keys, or gateway not restarted | `e2e_check.py` (`langfuse.tracing`), `HERMES_LANGFUSE_DEBUG=true`, read `agent.log` |
| 401 from Langfuse | keys from another project | use the `langfuse-init` pair |
| traces without tokens | endpoint returns no `usage` | test: `curl .../chat/completions` with `"stream":true,"stream_options":{"include_usage":true}` must end with a `usage` object; enable usage in the serving stack |
| cost 0 | no model price / pattern mismatch | `bootstrap.py --model <exact id> --input-price ...` |
| ClickHouse pods pending | operator / cert-manager missing or no storage | `install.sh` step 1, storage class |
| Langfuse down | — | Hermes keeps working; traces of that period are lost |
