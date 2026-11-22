# Task: let the Hermes bot explain its own cron messages in Mattermost (Hermes v0.22.5)

Give this file to the coding agent as the task. Everything below "Verified" was checked in the Hermes
v0.22.5 source. Do not add anything that is not listed here.

## Goal
A team member tags the bot in the Mattermost channel and asks "explain this morning's summary" /
"what is this anomaly" / "why did you send this". The bot answers from the message it actually sent
and the data behind it.

## Why it fails today
Every cron run is a separate, isolated session. Its message is posted to the channel but is not part
of the channel conversation, so the bot that answers a tag has never seen it.

## Verified Hermes v0.22.5 behavior (`cron/scheduler_delivery.py`, `gateway/mirror.py`, `hermes_state_sessions.py`)
- A cron message enters a chat conversation only through the delivery mirror. It is on for a job when
  the job's `attach_to_session` is `true`, or, if the job does not set it, when global
  `cron.mirror_delivery` is `true`. For `--deliver mattermost` (the home channel) the global flag is
  enough. `attach_to_session` is required only for explicit `mattermost:<chat_id>` targets.
- `attach_to_session` has no CLI flag in v0.22.5 (or v0.23.3) and `hermes cron list` does not show it.
  `cron_settings.py` (below) sets and checks it through Hermes' own `cron.jobs.update_job`.
- Mattermost has neither of the two reliable paths Hermes has: it cannot open a thread per delivery
  (`create_handoff_thread` not implemented) and does not support the `in_channel` surface (only Slack
  sets `supports_inchannel_continuable`). So Hermes falls back to looking up an existing live session
  for that channel, without a user:
  - no live session in the channel yet (nobody talked to the bot there, or after `/new`/`/reset`) →
    nothing written;
  - live sessions in that channel (the channel session plus any thread sessions) belong to more than
    one distinct user → nothing written ("never another participant's session");
  - otherwise it is appended to the most recently started live session of that channel, which may be a
    thread session rather than the channel itself.
  A miss is silent (debug log `Mirror: no session found`). v0.23.3 changed the lookup to probe the
  channel session first.
- `group_sessions_per_user: false` (top level in `config.yaml`; default `true`, so it must be written)
  makes the channel one shared session. With `true` every user has a session in the channel and the
  lookup above always finds several users → never mirrored. DMs are one session per DM either way.
- `MATTERMOST_REPLY_MODE`: `off` (default, replies in the channel) or `thread` (each reply in a thread
  with its own session). Use `off`: thread sessions from several users also block the mirror.
- There is no time-based session reset in v0.22.5 (no `session_reset`/`idle_minutes`/`at_hour` in the
  code). Sessions reset only with `/new` or `/reset` in the chat; long conversations are compressed.
- Every run is saved to `$HERMES_HOME/cron/output/<job_id>/` (silent runs too).
- `$HERMES_HOME/cron/` is Hermes' own store (`jobs.json` + run output). Never delete or replace it.

**Conclusion:** on Mattermost v0.22.5 the mirror is best effort. The reliable mechanism is the skill
section in step 4 (read `cron/output`). Configure the mirror too, but never depend on it.

## Changes
1. `config.yaml`:
   ```yaml
   group_sessions_per_user: false   # top level
   cron:
     mirror_delivery: true          # home-channel deliveries are mirrored when the lookup succeeds
   ```
2. Env (`.env` / k8s Secret): `MATTERMOST_REPLY_MODE` removed or `off`; `MATTERMOST_HOME_CHANNEL` set.
3. The bash script that creates the cron jobs:
   - Every job that posts to the channel uses `--deliver mattermost`.
   - If the script or the container entrypoint runs `rm -rf` / `cp -r` over `$HERMES_HOME/cron`, remove
     that. It deletes all jobs, their settings and run history on every run.
   - With `cron.mirror_delivery: true` (step 1) home-channel jobs need nothing more. Only if a job
     delivers to an explicit `mattermost:<chat_id>`, or you want the setting pinned per job even if the
     global flag changes, add `cron_settings.py` (below) next to the bash script and as the last line:
     ```sh
     python3 "$(dirname "$0")/cron_settings.py" --attach <job names people ask about>
     ```
     Use the exact `--name` values, e.g. `--attach daily-summary anomaly-scan grafana-alerts`.
     Exit code 1 + `MISSING` means a name does not match a job. Fix the name, do not ignore it.
4. The skill that answers chat questions: add this section at the end of its `SKILL.md`
   (add the project's own data files behind the messages to step 1):
   ```markdown
   ## Your own messages

   Scheduled messages (daily summary, anomaly findings, alerts, ticket replies) come from separate cron
   runs. When someone asks about one ("explain the summary", "what is this anomaly", "why did you say X"):
   1. If it is already in this conversation (a `[Cron delivery: ...]` turn or a reply to it), use it.
      Otherwise find it: `ls -t "$HERMES_HOME"/cron/output/*/* | head -20` and read the file matching the
      job and time asked about.
   2. Answer from that text, not from memory. Quote the line being explained, then the evidence behind it.
   3. If asked whether it is still happening, run one query now and say so.
   4. If no matching output exists, say exactly that and which files you checked. Never reconstruct a
      message you cannot find.
   ```
5. `SOUL.md` (always in the prompt, so it works even if the model does not load the skill), add:
   ```markdown
   - Asked about a message you posted (summary, anomaly, alert, ticket reply) and it is not in this
     conversation: run `ls -t "$HERMES_HOME"/cron/output/*/* | head -20`, read the matching file, and answer
     from it. Never say you do not know before checking. Details: <that skill>, section *Your own messages*.
   ```

## Optional: when the internal LLM returns 503 (all keys exist in v0.22.5)
```yaml
agent:
  api_max_retries: 3        # default 3: retries on 5xx
  auto_recovery_cycles: 5   # default 5: then waits 15/30/60/60/60 s with a visible countdown
fallback_providers:         # only if a second endpoint exists: used on 500/502/503 after retries
  - provider: custom
    model: <backup model>
    base_url: http://<backup-endpoint>/v1
    key_env: BACKUP_LLM_KEY
```
Without a backup endpoint the two `agent` defaults already apply; change nothing.

## Constraints
- Change only what is listed. No new services, no MCP, no other scripts.
- Do not invent config keys, flags or paths. If something does not match this version, stop and report.
- No secrets in git.

## Verify on the running system, then report
1. `config.yaml` has `cron.mirror_delivery: true` and `group_sessions_per_user: false`; if `cron_settings.py` is used, `--check --attach <same names>` prints `OK` for every job.
2. `ls -t "$HERMES_HOME"/cron/output/*/* | head` shows files. If the layout differs, fix the glob in the skill and SOUL.md.
3. Restart the gateway, then restart again and repeat step 1: still `OK` (nothing wipes the cron store).
4. Tag test: `@bot run ls -t $HERMES_HOME/cron/output/*/* | head -5`. A file list = tool calling and
   terminal work. Plain text with no command run = the model endpoint's tool calling or the terminal
   permission is the problem, not the skill.
5. After the next delivery of an attached job: gateway debug log shows `Mirror: wrote to session`, and
   `@bot explain the last <job> message` quotes it.
6. Report each step's result and anything that did not match this file.

## cron_settings.py (add as is)
```python
#!/usr/bin/env python3
"""Apply the per-job cron settings that `hermes cron create` has no flag for, and verify them.

Hermes v0.22.5 (and v0.23.3) keeps `attach_to_session` on the job but has no CLI flag for it (only the
agent's cronjob tool), and `hermes cron list` does not show it. `failure_deliver` also has a CLI flag
(`--failure-deliver`); it is handled here too so cron/*.json can carry it. This reads the wanted
values from cron/*.json, matches live jobs by name, and writes through Hermes' own
cron.jobs.update_job (same lock as the CLI).

  cron_settings.py [CRON_DIR]           apply, then print each job's live values
  cron_settings.py --check [CRON_DIR]   only print; exit 1 if a live job differs from cron/*.json

No JSON specs (jobs built by a bash script with `hermes cron create`)? Name the jobs instead:
  cron_settings.py [--check] --attach daily-summary anomaly-scan grafana-alerts
"""
import glob
import json
import os
import shutil
import sys

SETTINGS = ("attach_to_session", "failure_deliver")


def _hermes_python():
    """Interpreter from the `hermes` launcher's shebang, e.g. /opt/hermes/.venv/bin/python."""
    exe = shutil.which("hermes")
    if not exe:
        return None
    with open(exe, "rb") as f:
        first = f.readline().decode(errors="ignore")
    if not first.startswith("#!"):
        return None
    parts = first[2:].split()
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
    return shutil.which(parts[0]) if parts and "python" in parts[0] else None


try:
    from cron import jobs as J
except ImportError:
    py = _hermes_python()
    if py and not os.environ.get("_CRON_SETTINGS_REEXEC"):
        os.environ["_CRON_SETTINGS_REEXEC"] = "1"
        os.execv(py, [py, *sys.argv])
    sys.exit("cron_settings: cannot import Hermes (cron.jobs). Run it with the Python that runs `hermes`.")


def wanted(cron_dir):
    for f in sorted(glob.glob(os.path.join(cron_dir, "*.json"))):
        with open(f) as fh:
            spec = json.load(fh)
        yield spec["name"], {k: spec[k] for k in SETTINGS if k in spec}


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if args and args[0] == "--attach":
        if len(args) < 2:
            sys.exit("cron_settings: --attach needs at least one job name")
        specs = [(name, {"attach_to_session": True}) for name in args[1:]]
    else:
        cron_dir = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cron")
        specs = list(wanted(cron_dir))
    live = {j.get("name"): j for j in J.list_jobs(include_disabled=True)}
    bad = 0
    for name, want in specs:
        job = live.get(name)
        if job is None:
            print(f"MISSING  {name}: not scheduled")
            bad += 1
            continue
        diff = {k: v for k, v in want.items() if job.get(k) != v}
        if diff and not check:
            job = J.update_job(job["id"], diff) or job
            diff = {k: v for k, v in want.items() if job.get(k) != v}
        state = "DIFF" if diff else "OK"
        bad += bool(diff)
        values = " ".join(f"{k}={job.get(k)!r}" for k in SETTINGS)
        print(f"{state:8} {name}: deliver={job.get('deliver')!r} {values}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```
