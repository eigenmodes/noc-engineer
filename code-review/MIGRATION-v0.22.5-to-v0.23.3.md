# Migration: Hermes v0.22.5 → v0.23.3 (Docker / Kubernetes, Mattermost)

For the coding agent or the operator doing the upgrade. Every statement was checked in the source of both
tags (`code-review/hermes-agent` is v0.22.5; v0.23.3 is tag `v0.23.3` of NousResearch/hermes-agent) and
in v0.23.3's `website/docs/getting-started/updating.md`. If something on the system does not match, stop.

## 0. Decide first
- **Gain:** the cron mirror on Mattermost becomes reliable enough to count on (see 2.1). Everything else
  this agent uses already works on v0.22.5.
- **Cost:** a one-way change to `state.db`. **Rollback = restore a backup**, not "start the old image".
- **No gain:** `attach_to_session` still has no CLI flag and `hermes cron list` still does not show it.
  Mattermost still has no thread or in_channel cron surface.

## 1. What changes (only what touches this agent)

| Area | v0.22.5 | v0.23.3 | Action |
|---|---|---|---|
| `state.db` schema | 32 | 33, migrated automatically on first open | **Backup before** (step 3). The old release cannot run on it afterwards |
| Session runtime | gateway + separate runners | one gateway owns every session (CLI, cron, API...). Input that was mid-turn at the cutover restart becomes `unknown` and is **not replayed**; a cron delivery claimed but unfinished is recorded `delivery_failed` | Upgrade when no job is running. After start, check `hermes cron list` / last runs; acknowledge stuck inputs with `hermes sessions discard <session> --yes` |
| Rollback | — | "Rolling back is unsupported once the new gateway has written state.db." An old release refuses to delete/prune those sessions; a running old gateway on an upgraded store stops itself within ~30 s | Rollback only by restoring the backup (step 7) |
| Config schema | `_config_version` 51 | 54. Migrated automatically: v52 drops `browser.backend` / `browser.extension_control` (moves `AGENT_BROWSER_*`), v53 `clarify_timeout` 3600 → 90, v54 `prompt_caching.cache_ttl` → `auto` | Nothing for this agent's config. Note: `start.sh` replaces `config.yaml` on every start, so the stamped `_config_version` is rewritten each boot and the migration notes may repeat (harmless) |
| Config keys this agent uses | `group_sessions_per_user`, `cron.mirror_delivery`, `cron.wrap_response`, `monitoring.*`, `agent.api_max_retries`, `agent.auto_recovery_cycles`, `memory.*_char_limit` | all still present | none |
| Top-level config sections | has `honcho` | `honcho` removed (memory provider moved to the plugin catalog); new `hosted_rooms`, `webapp` | Only if `config.yaml` has `honcho:` |
| Cron mirror lookup (`gateway/mirror.py`) | scans live sessions of the chat; several distinct users (channel + threads) → nothing written; otherwise the newest session, possibly a thread | probes the channel's own session first ("General" room, then the flat session, then a thread keyed on its id); none → nothing | **Main gain.** Still needs a live channel session and `group_sessions_per_user: false` |
| Cron job fields | — | new: `timezone`, `grace_minutes`, `catch_up`, per-job `wrap_response`; CLI `--timezone`, `--grace-minutes` | Optional. `TZ=Asia/Jerusalem` in the pod keeps working |
| Cron CLI | `--continuity`, `--failure-deliver`; no `attach_to_session` flag | same | `cron_settings.py` keeps working (`list_jobs(include_disabled=)`, `update_job` unchanged) |
| Mattermost | env `MATTERMOST_URL/TOKEN/ALLOWED_USERS/HOME_CHANNEL/REPLY_MODE` | same names; SSRF check on file/image downloads; bot-user detection | none |
| Docker | s6-supervised `gateway run` | same | none |

## 2. Expected effect on this agent
2.1 Cron messages to the home channel get into the channel conversation whenever the channel has a live
    session, even if thread sessions exist. Still not when nobody has written in the channel since `/new`.
    The `cron/output` lookup in the chat skill stays: it is still the path that always works.
2.2 Nothing else in the repo needs a code change for v0.23.3.

## 3. Backup (mandatory)
```sh
kubectl scale deploy/hermes-noc --replicas=0          # stop: no writes during the copy
# A) volume snapshot of PVC hermes-noc-home (preferred, if the storage class supports it), or
# B) copy the whole HERMES_HOME from a helper pod that mounts the PVC:
tar czf hermes-home-v0.22.5-$(date +%F).tgz -C /data hermes
```
`hermes backup` (zip of the home) also exists in v0.22.5; with the gateway stopped either works. Quick
`/snapshot` skips a `state.db` larger than 1 GiB, so do not rely on it alone.

## 4. Test on a copy first
1. Restore the backup into a **new** PVC.
2. Deploy a second Deployment (different name) with the v0.23.3 image on that PVC. Give it a **different
   Mattermost bot token or no Mattermost env at all**: two gateways on one bot token both answer.
   Do not run two pods on the same PVC.
3. Watch the first start: config migration notes, `state.db` migration, no traceback.
4. Run `code-review/HEALTH-CHECKLIST.md` against it (sections 1–6 and 9).
5. Cron: `hermes cron list` shows every job enabled; `python3 /opt/noc-engineer/cron_settings.py --check /opt/noc-engineer/cron` → all `OK`; trigger one job (`hermes cron run <id>`) and check `cron/output/<id>/`.

## 5. Build
```sh
# Dockerfile: ARG HERMES_IMAGE
docker build -f deploy/Dockerfile --build-arg HERMES_IMAGE=nousresearch/hermes-agent:<v0.23.3 tag> \
  -t <registry>/noc-engineer:0.3.0-h0.23.3 .
docker run --rm <registry>/noc-engineer:0.3.0-h0.23.3 hermes --version     # must say 0.23.3
docker push <registry>/noc-engineer:0.3.0-h0.23.3
```
Use the image tag that `hermes --version` confirms; do not use `latest`.

## 6. Production cutover
1. Pick a window with no 09:00 summary and let running jobs finish (`hermes cron list`).
2. Backup again (step 3) right before; keep it until v0.23.3 has run for a week.
3. `kubectl set image deploy/hermes-noc hermes=<registry>/noc-engineer:0.3.0-h0.23.3` (the Deployment
   uses `Recreate`, so the old pod stops before the new one opens `state.db`).
4. Check: pod ready; gateway log shows Mattermost connected; `hermes cron list`; `hermes monitoring status`;
   Prometheus `hermes_gateway_up == 1`.
5. Mirror check: write once in the channel, wait for the next delivery, gateway debug log shows
   `Mirror: wrote to session`; `@bot explain the last <job> message` quotes it.
6. Update repo: `distribution.yaml` `hermes_requires: ">=0.23.3"` only if you start using a 0.23-only
   feature (e.g. job `timezone`); otherwise leave `>=0.22.5`. Re-pin the submodule:
   `git -C code-review/hermes-agent fetch --depth 1 origin tag v0.23.3 && git -C code-review/hermes-agent checkout v0.23.3`,
   and regenerate `code-review/HERMES-REFERENCE-*.md` from that tag.

## 7. Rollback
Not by switching the image back on the same PVC (the old release refuses parts of an upgraded store).
1. `kubectl scale deploy/hermes-noc --replicas=0`
2. Restore the PVC from the step-3 snapshot / tarball.
3. `kubectl set image deploy/hermes-noc hermes=<previous image>` and scale back to 1.
Sessions and messages created after the upgrade are lost.

## Done means
- `hermes --version` = 0.23.3 in the pod; backup kept; health checklist without P0/P1 failures;
  every cron job enabled and producing `cron/output`; Mattermost answers; mirror verified once (step 6.5).
