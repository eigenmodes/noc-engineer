# Session isolation and load: guide for the implementing LLM

**Bottom line for the owner.** Conversations do not mix between users, and user load does not crash Hermes.
Three gaps remain:
1. persistent memory is shared;
2. a second message interrupts a running answer;
3. the LLM server is the bottleneck under load.

Close them, then prove everything with the tests below.

Every fact here was verified in the Hermes source of **v0.22.5 and v0.23.5** (latest tag on 2026-11-28).
Re-verify on the deployed version before acting. Where to look: `guides/HERMES-STRUCTURE.md`.

---

## 1. What is isolated, what is shared

| Layer | Scope | Source |
|---|---|---|
| Conversation history | Per session key `<platform>:<chat_type>:<chat_id>[:<thread_id>][:<user>]`. DM = per user. Channel = one shared session (because `group_sessions_per_user: false`). Thread = per thread | `gateway/session.py::build_session_key` |
| Reply routing | Back to the originating chat/thread | Mattermost adapter |
| Concurrent turns | Each turn on its own thread; no cross-session queue | gateway runner; `max_concurrent_sessions` (default unset) REJECTS over-cap turns, it does not queue |
| Same-session second message | `display.busy_input_mode`: `interrupt` (default) / `queue` / `steer` | `hermes_cli/config_defaults.py` |
| **Persistent memory** | **Per profile, injected into every session** | `memory.memory_enabled`, `memory.user_profile_enabled` |
| Cron | `cron.max_parallel_jobs` (default unbounded; env `HERMES_CRON_MAX_PARALLEL`) | `hermes_cli/config_defaults.py` |
| Other bots | The adapter ignores only its own posts | `plugins/platforms/mattermost/adapter.py` |

The only real cross-user leak path is **persistent memory**. Channel sharing is intended.

---

## 2. Changes

Apply them with `deploy/upgrade_settings.py apply --recommended`. The values live in `deploy/settings-lock.yaml`.

| # | Setting | Value | Status |
|---|---|---|---|
| 1 | `display.busy_input_mode` | `queue` | recommended. Follow-ups wait instead of cutting off the answer |
| 2 | `cron.max_parallel_jobs` | `1` | recommended. Cron stops competing with people for the LLM |
| 3 | `max_concurrent_sessions` | leave unset | A cap would reject users. Throttle at the LLM server instead |
| 4 | `fallback_providers` | one second endpoint | recommended. See `guides/review/PERFORMANCE.md` §3.8 |
| 5 | `memory.memory_enabled` | `false` on any profile customers reach | **owner decision.** Ask, record, then apply |
| 6 | `MATTERMOST_REPLY_MODE` | `thread` | **owner decision.** It changes the shared channel context. Recommend it, do not apply |
| 7 | LLM server parallel capacity (vLLM `max_num_seqs`) | number from the model team | **ask the owner.** Record it; it is the real concurrency limit |

Never change `group_sessions_per_user: false`.

---

## 3. Prove isolation (record each result in `PRODUCTION-STATUS.md`)

Run on a test bot, or in a quiet hour with test users.

- **I-1:** Two DMs at once, different topics (server X / rule Y). Each answer covers only its own topic.
- **I-2:** In DM B ask "מה המשתמש השני שאל?". It must not reveal DM A.
- **I-3:** 8 DMs within 10 s, each with a unique marker word. Every reply lands in the right DM, holds only its own
  marker, and none is missing.
- **I-4 (memory):** In DM A state a fake fact ("the code for customer Z is 4711"). Later ask for it in DM B.
  If it leaks, memory is shared, so item 5 is needed. Remove the fake fact afterwards (`/memory` or the memory file).
- **I-5:** Two channel messages 2 s apart. With `queue`, both are answered in order and neither is cut off.

## 4. Prove stability (record the numbers)

- **L-1:** 8 concurrent DMs + 1 channel question while the anomaly scan runs. Record time to first reply,
  time to final answer, LLM 5xx, fallback activations, and gateway CPU/RAM.
- **L-2:** 15 concurrent DMs. No crash or restart. Every user gets an answer or a clear error; no silent drop.
- **L-3:** Block the primary LLM during L-1. Answers continue through the fallback.
- **L-4:** Restart the gateway pod during an answer. The bot answers again after restart. Record what happened to
  the interrupted turn.

**Pass:** no crash, no cross-routed or lost reply, no leak in I-1..I-4. The owner sets latency targets from the
L-1 numbers.

## 5. Report

A short Hebrew summary for the owner, bottom line first:
- isolated: yes or no, with evidence;
- stable under N users: yes or no, with numbers;
- the open owner decisions (items 5, 6 and 7).
