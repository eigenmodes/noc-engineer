---
name: customer-question
description: "Answer questions from the team or customers in Mattermost about their servers, rules, loss, load or alerts, and explain messages the agent itself posted (daily summary, anomaly, alert, ticket)."
---

# Questions in Mattermost

Typical: "Is there loss on my server?", "Why did rule X stop matching?", "Was there maintenance last night?"

1. Identify what is asked about: server, rule, customer, time window. If one essential fact is missing, ask one short question.
2. Load `noc-environment`; query with `noc-tools`. Compare with last week or the window before.
3. Answer:
   - first line: the direct answer (yes / no / where)
   - 2-4 lines of evidence with numbers and time window
   - what you could not check, if anything
4. Never paste raw JSON or internal hostnames the asker did not mention. Never promise changes; you are read-only.

## Your own messages

Scheduled messages (09:00 summary, anomaly findings, Grafana alerts, ticket replies) are written by separate cron runs, so they may not be in this conversation. When someone asks about one ("explain the summary", "what is this anomaly", "why did you say X"):
1. Find what you posted. Newest cron outputs first:
   `ls -t "$HERMES_HOME"/cron/output/*/* | head -20` and read the file matching the job and time asked about.
   Raw data behind it: `$HERMES_HOME/data/noc/anomalies.jsonl` (findings), `anomaly_runs.jsonl` (scan runs), `audit.jsonl` (Jira comments).
2. Answer from that file, not from memory. Quote the line being explained, then the evidence behind it.
3. If asked whether it is still happening, run one `noc-tools` query now and say so.
4. If no matching output exists, say exactly that and which files you checked. Never reconstruct a message you cannot find.
