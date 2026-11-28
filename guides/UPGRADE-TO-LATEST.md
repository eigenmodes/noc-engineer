# Upgrade Hermes to the latest version, keeping every setting: guide for the implementing LLM

**Goal:** move to the newest stable Hermes, keep all our settings, adopt the new options that help us,
and keep a tested rollback.

**Latest checked:** tag **v0.23.5** (commit a428f534, 2026-11-27). Config schema 51 (v0.22.5) → 54.
`state.db` schema 33, the same as v0.23.3. The one-way 32→33 step happens when you come from v0.22.5.
Before upgrading, re-check that there is no newer tag:
`git ls-remote --tags https://github.com/NousResearch/hermes-agent.git 'v0.2*' | grep -v canary`
Use only plain `vX.Y.Z` tags, never `+canary`.

Files used here:
- `deploy/settings-lock.yaml`: every setting we own, with its status (required / recommended / owner_decision).
- `deploy/upgrade_settings.py`: `snapshot`, `check`, `apply [--recommended]`, `diff-defaults`.
- `guides/MIGRATION-v0.22.5-to-v0.23.3.md`: the state.db one-way step and breaking changes up to v0.23.3.

---

## 0. Rules
- Never invent keys. A key is real only if it is in the new version's `hermes_cli/config_defaults.py`
  (or gateway config / docs). `hermes config set` validates keys. Use it, never hand-edit YAML for new keys.
- Never apply `owner_decision` items. Report them.
- Backup first. The `state.db` migration from v0.22.5 is one-way.
- Do not change `group_sessions_per_user: false`.

## 1. Before (on the running version)
1. `hermes --version` → record it.
2. `python3 deploy/upgrade_settings.py snapshot` → copies config.yaml + the version into `$HERMES_HOME/backups/`.
3. Back up `state.db` and `$HERMES_HOME/data/`, with the gateway stopped or scaled to 0 (`guides/review/RUNBOOK.md`).
4. `python3 deploy/upgrade_settings.py check` → must show 0 required failures. Fix those first.
5. Dump the current defaults:
   `python3 -c "import json,hermes_cli.config_defaults as c; print(json.dumps(c.DEFAULT_CONFIG, default=str))" > /tmp/def_old.json`

## 2. Read what changed
1. Get the new version's source (submodule `guides/hermes-agent` → checkout the new tag) and dump its defaults to
   `/tmp/def_new.json` the same way.
2. `python3 deploy/upgrade_settings.py diff-defaults /tmp/def_old.json /tmp/def_new.json`:
   - **REMOVED / renamed:** if any key from `settings-lock.yaml` or our `config.yaml` is in this list, find its
     replacement in the new source and update the lock file. Stop until it is resolved.
   - **ADDED:** list the additions that matter to us (sessions, cron, gateway, Mattermost, approvals, memory,
     monitoring, fallback, display), with a one-line reason each. Propose them to the owner; do not enable them
     silently.
   - **DEFAULT changed:** for each one we do not pin, decide whether the new default is OK. If not, add it to
     `settings-lock.yaml`.
3. Read the release notes of every tag between the old and the new version (GitHub releases page). Note
   breaking changes, Mattermost changes, cron changes and state.db changes.

### 2.1 New options v0.22.5 → v0.23.5 already reviewed (propose to the owner, apply only after OK)
Verified in `hermes_cli/config_defaults.py` and the Mattermost adapter of v0.23.5. None of these keys exist in v0.22.5,
so add them to `settings-lock.yaml` only after the upgrade.

| Key | Default | Proposal | Why |
|---|---|---|---|
| `approvals.approvers` | `["*"]` = any admitted member | list of team-lead Mattermost user IDs, or `[]` (requester + admins) | Today any allowed user, customers included, may answer an approval or clarify prompt |
| `skills.index_desc_limit` | `60` chars (range 60..1024) | `200` | Skill descriptions are cut to 60 chars in the index, so the model picks skills worse. Costs a few tokens per turn |
| `compression.prepare_ahead` | `false` | `true` (test under load) | The shared channel session grows. The next summary is written in the background, so there is no compaction pause on a user's turn. It adds one background LLM call |
| `agent.clarify_timeout` | was 3600, now **90** s | keep 90, or 300 for customer DMs | A behavior change: an unanswered clarify question now expires after 90 s. A new message from the user cancels it |
| `MATTERMOST_BOT_USERS` (env) / `bot_users` | empty | user IDs of other bots that post in our channels | Marks them as bots, so `gateway.bot_loop_guard` (on by default, `max_hops: 4`) stops bot-to-bot loops |
| `delegation.auto_resume` | `false` | keep `false` | It resumes child tasks unattended and spends tokens |
| `runtime.malloc_arena_max` | `4` | keep | Lower gateway RAM, already on by default |
| `security.redact_phone_numbers` | `true` | keep | Phone numbers are redacted |

Not relevant to us: `webapp.*`, `hosted_rooms.*`, `auxiliary.group_router.*`, `voice.*`, `telegram.*`, `browser.*`,
`vault.*`, `worktrees.*`, `prompt_caching.*` (the vLLM prefix cache works server-side).

## 3. Upgrade (test namespace first)
1. Pin the image to the exact tag (`nousresearch/hermes-agent:vX.Y.Z`). Confirm the tag exists in the registry.
   Never use `latest` or `stable` in production.
2. Start it on a COPY of `$HERMES_HOME` (restored backup) in a test namespace.
3. `hermes config check` → resolve "missing" and "stale" items.
   `hermes config migrate` adds new options interactively: run it, and accept only what step 2 approved.
4. `python3 deploy/upgrade_settings.py apply` → re-applies the required settings with `hermes config set`.
   Add `--recommended` only for the recommended items the owner approved.
5. `python3 deploy/upgrade_settings.py check` → 0 required failures, no `UNKNOWN_KEY`, no `STALE?` left unexplained.
6. Run `deploy/e2e_check.py` (all green), the evals (no drop), and `guides/SESSION-ISOLATION-AND-LOAD.md` I-1..I-5 and L-1.
7. Check that cron jobs still exist with the same schedules (`hermes cron list`), and that `attach_to_session`
   still holds (`deploy/cron_settings.py`).

## 4. Production
1. Stop the gateway (`strategy: Recreate`, one replica), take a fresh backup, deploy the pinned tag, run steps 3.3–3.5.
2. Watch for 24 h: `hermes_gateway_up`, `hermes_platform_up{hermes_platform="mattermost"}`, the cron heartbeat,
   LLM errors, and Langfuse latency.

## 5. Rollback
Previous image tag plus the backups from step 1. Restore BOTH `state.db` and config.yaml, because an older Hermes
cannot open a migrated `state.db`. Then `upgrade_settings.py check`.

## 6. Report to the owner (Hebrew, bottom line first)
- the version moved from and to;
- settings kept: the `check` output, 0 failures;
- new options proposed and the decisions taken;
- keys renamed or removed and how they were handled;
- test results;
- the rollback point.

Update `settings-lock.yaml` and this guide's "Latest checked" line in the same commit.
