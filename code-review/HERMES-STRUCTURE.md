# Task: bring a Hermes agent project to the structure Hermes recommends (v0.22.5)

Give this file to the coding agent. Facts here come from the Hermes v0.22.5 docs and source
(`code-review/HERMES-REFERENCE-v0.22.5.md` has the official text; `code-review/hermes-agent/` is the v0.22.5 source). Do not add anything that is
not here or there. If the project does not match an assumption below, stop and report.

## 1. Where it must end up

```
<agent>/                      # repo root = the profile (a "profile distribution")
├── distribution.yaml         # manifest: name, version, hermes_requires, env_requires, distribution_owned
├── SOUL.md                   # identity and voice only
├── config.yaml               # model, provider, agent/session/cron/monitoring settings
├── cron/
│   └── jobs.json             # every scheduled job, one file (see 3.3)
├── scripts/                  # pre-run scripts used by cron jobs (stdout = the job's input)
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md          # frontmatter (name, description, ...) + procedure
│       ├── scripts/          # helper scripts the skill calls
│       ├── references/       # longer docs the skill reads on demand
│       ├── templates/        # output formats
│       └── assets/           # data/config files
├── mcp.json                  # only if MCP servers are used
├── .gitignore                # see 3.6
├── README.md                 # for humans
├── deploy/                   # Dockerfile, entrypoint, k8s, alerts (not installed into the profile)
├── code-review/              # notes, checklists and Hermes reference for coding agents (not installed)
└── tests/                    # (not installed)
```

What lives in `HERMES_HOME` at runtime and is **never** in git: `.env`, `auth.json`, `memories/`
(`MEMORY.md`, `USER.md`), `sessions/`, `state.db*`, `logs/`, and every file under `cron/` other than
`jobs.json` (`cron/output/`, locks, ledgers).

## 2. What each file is for (Hermes "Which file does what")
| File | Holds | Written by |
|---|---|---|
| `SOUL.md` | identity, tone, directness, how to handle uncertainty and disagreement. Not paths, not repo conventions, not workflows | you |
| `skills/*/SKILL.md` | procedures: when to use (frontmatter `description`), steps, commands | you |
| `AGENTS.md` / `.hermes.md` | project instructions, loaded from the agent's working directory | you |
| `MEMORY.md`, `USER.md` | facts the agent learned / about users. Caps: 2,200 / 1,375 chars. Frozen snapshot at session start | the agent |
| `config.yaml` | settings | you |
| `cron/jobs.json` | job definitions | you (generated, see 3.3) |

Only one project context file loads per session: `.hermes.md` → `AGENTS.override.md` → `AGENTS.md` →
`CLAUDE.md` → `.cursorrules`. `SOUL.md` always loads, from `HERMES_HOME` only. A coding-agent `CLAUDE.md`
in the agent's working directory would be loaded into the bot: keep it out of that directory.

## 3. Steps

### 3.1 `distribution.yaml`
```yaml
name: <agent>
version: 1.0.0
description: "<one line>"
hermes_requires: ">=0.22.5"
env_requires:
  - {name: MATTERMOST_URL, description: "...", required: true}
  # one entry per env var the agent needs; required: false + default for optional ones
distribution_owned: [SOUL.md, config.yaml, skills/, scripts/, cron/jobs.json, distribution.yaml]
```
Default `distribution_owned` is `SOUL.md, config.yaml, mcp.json, skills, cron, distribution.yaml`.
`scripts/` is not in the default, so list it if cron jobs use pre-run scripts.

### 3.2 `SOUL.md`
Keep identity, voice and the hard rules about uncertainty (cite evidence, never invent values, say what
was not checked). Paths, commands and workflows go into skills. A short "what you handle → which
skill" list may stay (it helps weaker models pick the skill); every skill's frontmatter `description`
must still say when to use it. Target: one screen.

### 3.3 Cron: pick one, not both
**A. Not installed with `hermes profile install/update` (one deployment you manage):** keep the `.sh`
with `hermes cron create`, but it must:
1. create a job only if no job with that name exists (re-running must not duplicate);
2. apply changes to existing jobs with `hermes cron edit <id> ...` (or remove + create);
3. end with `python3 cron_settings.py --attach <job names>` (the CLI has no flag for
   `attach_to_session`; `hermes cron list` does not show it).

**B. Profile distribution (recommended when `hermes profile install/update` is used):** ship
`cron/jobs.json`. On update it is merged by job id: shipped definitions refresh in place, local jobs and
each job's paused/enabled state survive, new jobs arrive **paused**. Definition fields it carries:
`name, prompt, skills, skill, model, provider, base_url, script, no_agent, monitor_script, monitor_url,
context_from, schedule, schedule_display, deliver, origin, enabled_toolsets, workdir, attach_to_session,
reasoning_effort, failure_deliver`.
Generate it, do not hand-write it:
1. on a clean profile run the existing `.sh` once, then `cron_settings.py --attach ...`;
2. copy `$HERMES_HOME/cron/jobs.json` into the repo;
3. keep `id` and the definition fields above; delete runtime fields (`next_run_at`, `last_run_at`,
   `last_status`, `state`, `paused_at`, `paused_reason`, `created_at`, counters);
4. delete the `.sh` and `cron_settings.py`.

### 3.4 Entrypoint (container)
It must never delete or overwrite `$HERMES_HOME/cron/` (that is `jobs.json` + run history).
- With B: first boot `hermes profile install <path-to-repo-copy> -y`, later boots
  `hermes profile update <agent> --force-config` (`update` keeps the installer's `config.yaml` unless
  `--force-config`), then `hermes cron resume <id>` for jobs that must run, then
  `hermes -p <agent> gateway run`. A distribution cannot be installed as `default`, so the agent lives in
  `$HERMES_HOME/profiles/<agent>/`. Install accepts a local directory. Verify on a separate pod that
  `update` re-reads the local directory before using this in production.
- With A: copy only `SOUL.md config.yaml distribution.yaml skills scripts`, run the `.sh`, run the gateway.

### 3.5 `config.yaml` keys this agent needs (all exist in v0.22.5)
```yaml
group_sessions_per_user: false      # top level; one shared conversation per channel
cron: {mirror_delivery: true}       # best effort on Mattermost; see HERMES-UPDATE-PROMPT.md
agent: {api_max_retries: 3, auto_recovery_cycles: 5}   # defaults; 503 handling
# fallback_providers: [...]          # only if a second model endpoint exists
monitoring:
  gateway_health_export: {enabled: true}
  export: {otlp: {enabled: true, endpoint: "<collector>"}}
```
Check every key against the reference before adding anything else.

### 3.6 `.gitignore` (minimum)
```gitignore
auth.json
.env
.env.EXAMPLE
state.db*
memories/
sessions/
logs/
cron/*
!cron/jobs.json
skills/.*
```

## 4. Done means
1. `tree` matches section 1; nothing from the "never in git" list is tracked (`git ls-files`).
2. `SOUL.md` fits one screen and has no paths or workflows.
3. Every skill has a `SKILL.md` whose `description` says when to use it.
4. Cron (A): running the `.sh` twice leaves the same job count; `cron_settings.py --check --attach ...` → all `OK`.
   Cron (B): `cron/jobs.json` is the only file under `cron/` in git; after install + resume, `hermes cron list` shows every job enabled.
5. Restart twice: jobs, their settings and `cron/output/` history are still there.
6. In Mattermost: `@bot explain this morning's summary` quotes the real message.
7. `code-review/HEALTH-CHECKLIST.md`: no P0 or P1 failure.
8. Report: which cron option was used, every deviation from this file, and anything not verified.
