# Task: let the Hermes bot explain its own cron messages in Mattermost

Put this file at the root of the project and give it to the coding agent as the task.

## Goal
A team member tags the bot in the Mattermost channel (or replies to one of its messages) and asks
"explain the summary" / "what is this anomaly" / "why did you send this". The bot must answer from the
message it actually sent and the data behind it, not say it does not know.

## Why it fails today
Every cron run is a fresh, isolated session. Its delivery is not part of the channel conversation, so
when someone tags the bot in the channel, the bot has never seen that message.

## Verified Hermes behavior (docs + gateway/mirror.py). Do not assume anything beyond this.
- `group_sessions_per_user` is top-level in `config.yaml`. Default `true`: in a shared channel every user
  has their own session. `false` = one shared conversation for the whole channel. DMs are always one
  session per DM and are not affected.
- `MATTERMOST_REPLY_MODE`: `off` (default, flat messages in the channel) or `thread` (reply in a thread
  under the user's message; thread context is isolated from the channel).
- `cron.mirror_delivery` (global, default off) makes cron deliveries continuable. The per-job
  `attach_to_session` overrides it. The global flag alone never makes an explicitly addressed chat
  continuable; that needs `attach_to_session: true` on the job.
- On thread-capable platforms each delivery opens its own thread and the brief is seeded into that
  thread's session, so replying in that thread continues with full context. The docs do not say whether
  Mattermost is treated as thread-capable: check it on the live system.
- Mirroring into an existing session matches platform + chat_id (+ thread_id if given), then user_id.
  If several users have sessions in that channel and none matches, nothing is written (no error, debug
  log `Mirror: no session found`). If no session exists yet (for example right after a session reset),
  nothing is written either.
- Every run is saved to `$HERMES_HOME/cron/output/<job_id>/` (silent runs too), with the response as written.
- Delivery target `mattermost` = the Mattermost home channel (`MATTERMOST_HOME_CHANNEL`).

## Changes to make
1. `config.yaml` (top level): `group_sessions_per_user: false`. Keep the existing `cron.mirror_delivery: true`.
2. Env (`.env` / k8s Secret): `MATTERMOST_REPLY_MODE` removed or `off`. `MATTERMOST_HOME_CHANNEL` set.
3. Cron jobs (the `.sh` that creates them): every job delivers with `--deliver mattermost`.
   This Hermes version has no `attach_to_session`. Do not add it. Run `hermes cron edit --help` once and
   report whether a `--continuity` flag exists and what its help text says; do not enable it unless the help
   text says it makes deliveries continuable. The skill section in step 4 is the main mechanism; mirroring
   is a bonus. Existing jobs are not updated by re-running the `.sh`:
   edit them, or remove and recreate them (`hermes cron list`, `hermes cron remove <id>`).
4. The skill that answers chat questions: add this section at the end of its `SKILL.md`
   (add the project's own data files behind the messages to step 1):

   ```markdown
   ## Your own messages

   Scheduled messages (daily summary, anomaly findings, alerts, ticket replies) are written by separate
   cron runs, so they may not be in this conversation. When someone asks about one ("explain the summary",
   "what is this anomaly", "why did you say X"):
   1. If the message is already in this conversation (a reply to it, or a `[Cron delivery: ...]` turn), use it.
      Otherwise find it: `ls -t "$HERMES_HOME"/cron/output/*/* | head -20` and read the file matching the job
      and time asked about.
   2. Answer from that text, not from memory. Quote the line being explained, then the evidence behind it.
   3. If asked whether it is still happening, run one query now and say so.
   4. If no matching output exists, say exactly that and which files you checked. Never reconstruct a
      message you cannot find.
   ```
5. `SOUL.md` (always in the prompt, so it works even if the model does not load the skill): add
   ```markdown
   - Asked about a message you posted (summary, anomaly, alert, ticket reply) and it is not in this
     conversation: run `ls -t "$HERMES_HOME"/cron/output/*/* | head -20`, read the matching file, and answer
     from it. Never say you do not know before checking. Details: <that skill>, section *Your own messages*.
   ```

## Constraints
- Change only what is listed. No new services, no new scripts, no MCP.
- Do not invent config keys, flags or paths. If a flag does not exist on this version, say so.
- No secrets in git.

## Verify on the running system, then report
1. `ls -t "$HERMES_HOME"/cron/output/*/* | head` shows files. If the layout differs, fix the glob in the skill.
2. Restart the gateway. Trigger one job (`hermes cron run <id>` or wait for it).
3. Look at Mattermost: did the delivery open its own thread? (tells whether Mattermost is thread-capable here)
4. Gateway log at debug: `Mirror: wrote to session` (ok) or `Mirror: no session found`.
5. Ask in three ways and record each answer:
   a. reply inside the delivery's thread (if one opened): "explain this"
   b. tag the bot in the channel: "@bot explain this morning's summary"
   c. DM the bot the same question (expected to work only through the cron/output lookup)
6. Report: which of a/b/c worked, what `hermes cron edit --help` says about continuity, and anything not verified.
