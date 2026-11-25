# Premium user experience for the NOC agent (task for an LLM)

Goal: answers that feel fast, are clear, always follow the same structure, and behave like a good NOC
engineer. This file says **what** must happen and **where** to configure it. Settings marked ✔ were
verified against Hermes v0.22.5 (`guides/hermes-agent`, `guides/HERMES-REFERENCE-v0.22.5.md`).
Items marked **verify** were not tested on the live system. Do not invent config keys or flags.
Example messages are in Hebrew because the team writes in Hebrew; the agent answers in the user's language.

## 1. Six principles
| # | Principle | What the user feels |
|---|---|---|
| 1 | **Fast, or at least feels fast** | acknowledgement within seconds, text streams in, no long silence |
| 2 | **Conclusion first** | the first line answers the question |
| 3 | **Same structure every time** | the team reads an answer in one second |
| 4 | **Engineer, not chatbot** | asks only when a fact is missing, never guesses, says what it could not check |
| 5 | **Quiet when there is nothing to say** | automatic messages only for new findings |
| 6 | **Reliable on a bad day** | a clear message instead of silence or a crash when something is down |

## 2. Perceived speed

### 2.1 Immediate acknowledgement
Rule for `SOUL.md`:
```markdown
- Before any tool call in chat, reply with one short line that says what you are checking
  (object + window), in the user's language. Example: "בודק את srv1, הרמטיות בשעתיים האחרונות…".
  Do not repeat it later.
```
With thinking on, even this line costs one model round. The instant system-side notice comes from
`long_running_notifications` (2.2).

### 2.2 Mattermost display ✔
```yaml
streaming:
  enabled: true                      # Mattermost supports message edits: text appears as it is written
display:
  platforms:
    mattermost:
      tool_progress: 'off'           # no tool bubbles / script paths
      interim_assistant_messages: false
      long_running_notifications: true   # one "working on it" during long silences
      live_status: verb              # action only, no arguments
```

### 2.3 Fewer rounds
At most 3 model rounds per question, using one consolidated investigation command
(`guides/review/PERFORMANCE.md` §3.1). This matters more than any display setting.

## 3. Answer templates
Put the general structure in `SOUL.md` and each template in the matching skill. Rules for all:
- **Length:** one screen. Details only on request ("expand").
- **Language:** the user's. Technical terms (hop, rule, server names) stay as they are.
- **Numbers:** always with a baseline ("59% drop vs the same hour last week") and a time.
- **Status** categorical (`CONFIRMED` / `HIGH_CONFIDENCE` / `INCONCLUSIVE` / `INVESTIGATION_INCOMPLETE`), never percentages.
- **Evidence last**, short: query, window, value.
- One severity emoji at the start of the first line, no more: 🔴 fault, 🟠 suspicion, 🟢 OK, ⚪ inconclusive.

### 3.1 Investigation (team)
```
🔴 הבעיה ב-enrichment, לא בשרת. התחילה ב-13:42.
סטטוס: HIGH_CONFIDENCE

• איפה: enrichment, ירידה של 59% מול שבוע שעבר. ingress ו-capture תקינים
• למה: עדכון קונפיגורציה #881 ב-13:40, ו-312 שגיאות timeout ל-<service> אחריו
• מה עכשיו: לבדוק את #881 מול צוות ה-rules

ראיות:
• rule_rate{server="srv1"} 13:00–15:00: 0.41 מול 7d
• ECK <index>: "timeout" אחרי 13:42, 312 מופעים
לא נבדק: Argo (אין גישה)
```
Structure: severity + conclusion + onset / status / where / why / next step / evidence / not checked.

### 3.2 Customer answer
```
זיהינו ירידה בהתאמות בשרת שלכם srv1, החל מ-13:42.
הסיבה בבדיקה מול הצוות הרלוונטי, ועדכון יישלח בטיקט <JIRA-123>.
בשלב זה אין צורך בפעולה מצדכם.
```
No internal hop names, no queries, nothing about other customers (`guides/review/SECURITY.md` row 5).

### 3.3 Cron anomaly
```
🟠 [INV-0412] port_in_rate ירד ב-srv7: 0.38 מול שבוע שעבר (מ-10:35)
עוד 2 ממצאים: srv8, srv9 (אותו דפוס) · שאלו "@bot תסביר את INV-0412"
```
One line per finding, an ID to ask about, only new findings (`guides/WAKE-AGENT.md`).

### 3.4 Morning summary (09:00)
```
☀️ סיכום 24 שעות · 3 ממצאים חדשים · 1 עדיין פתוח
• 🔴 srv7 port_in ירידה מ-10:35, פתוח (INV-0412)
• 🟢 rule 4711 חזר לשגרה ב-16:20 (INV-0398)
• 🟠 Kafka lag עלה בלילה, נורמלי מ-05:10
סריקות: 288/288 הצליחו
```
5–8 lines. Open items first.

### 3.5 When something is unavailable
```
⚪ לא הצלחתי לבדוק עד הסוף: ECK לא זמין (timeout).
מה כן בדקתי: Prometheus (תעבורה ו-rule rate תקינים מול שבוע שעבר), Jira (אין טיקטים פתוחים על srv1).
אנסה שוב אם תשאלו בעוד כמה דקות.
```
Never silence, never "I don't know" without listing what was checked.

## 4. Engineer behavior
Rules for `SOUL.md`:
```markdown
- Ask at most one question, only when a required fact is missing (which server, which time). Otherwise act.
- Never answer "I don't know" without checking. Say what you checked and what you could not.
- Never state a value no tool returned.
- If a question is outside the NOC domain, say so in one line and who handles it.
- When asked about a message you posted, find it (cron/output, INV id) and quote it before explaining.
```

## 5. Audience
| Audience | How identified | Style |
|---|---|---|
| NOC team | on the team list (`skills/noc-environment`) | technical: hops, queries, full evidence |
| Customer | anyone not on the list, in a DM | plain and short, only their servers/tickets, with a ticket ID |
**Verify** the model sees the sender's identity. Without it neither audience style nor customer isolation works.

## 6. Automatic messages without flooding
- **Anomalies:** only new findings, one line each, grouped in one message.
- **Backend errors:** once per hour per error (`guides/WAKE-AGENT.md`).
- **`cron.wrap_response: false`** ✔: no header/footer around cron messages.
- **Morning summary:** what is open, what closed, one line on scan health.

## 7. Reliability
- Fallback model and `agent.api_max_retries: 1` (`guides/review/PERFORMANCE.md` §3.8).
- Template 3.5 for every partial failure.
- Kill switches ready (`guides/review/RUNBOOK.md`).

## 8. Measure the experience
| Metric | Where | Target |
|---|---|---|
| time to first sign (ack or text) | Langfuse, first generation | a few seconds |
| time to full answer | trace duration | trending down; compare before/after |
| rounds per question | generations per trace | ≤ 3 |
| unnecessary clarifying questions | manual trace sample | rare |
| satisfaction | 👍/👎 reactions → Langfuse score `user_feedback` | **verify** how to pass Mattermost reactions (does not exist today) |
| mistakes | `guides/review/EVALS.md` | 0 invented values, 0 leaks |

## 9. Implementation checklist
| # | Step | Where | Done when |
|---|---|---|---|
| 1 | Display and streaming (2.2) | `config.yaml` | no paths in chat, text streams |
| 2 | Ack rule (2.1) and engineer rules (4) | `SOUL.md` | every question gets a "checking…" line |
| 3 | Templates 3.1–3.5 | `SOUL.md` + skills (`customer-question`, `anomaly-scan`, `daily-summary`, `grafana-alert`) | 5 sample questions come out in the right structure |
| 4 | INV id in every cron message | `scripts/` + skills | "explain INV-…" works |
| 5 | `cron.wrap_response: false` | `config.yaml` | no wrappers around cron messages |
| 6 | Team list + customer style (5) | `noc-environment`, `SOUL.md` | manual scenario M4 in `guides/E2E-CHECKS.md` passes |
| 7 | Consolidated investigation command | `noc-tools` (`PERFORMANCE.md` §3.1) | ≤ 3 rounds |
| 8 | Fallback model | `config.yaml` (`PERFORMANCE.md` §3.8) | an answer, not silence, when the model is down |
| 9 | Measure before/after (8) | Langfuse, evals | numbers recorded |

## Constraints for the implementing LLM
- Change only what a checklist step names. Keep the repo flat; no new services.
- Run `python3 -m pytest -q tests` after every change.
- Report to the owner in Hebrew: what changed, what was verified, what was not.
