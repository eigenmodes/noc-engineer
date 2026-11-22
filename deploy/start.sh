#!/bin/sh
# Pod entrypoint. Same as `hermes profile update`: replace the distribution-owned files in HERMES_HOME
# (config.yaml included: the repo is the source of truth), schedule any cron job from cron/*.json that is not there yet, run the gateway.
set -eu
: "${HERMES_HOME:?HERMES_HOME must be set}"
SRC=/opt/noc-engineer
mkdir -p "$HERMES_HOME"
# Not cron/: in HERMES_HOME that is Hermes' own store (jobs.json, run output). Job specs stay in $SRC/cron.
for p in SOUL.md config.yaml distribution.yaml skills scripts; do
  rm -rf "${HERMES_HOME:?}/$p"
  cp -r "$SRC/$p" "$HERMES_HOME/$p"
done

# Langfuse tracing only when its keys are in the Secret. Catalog plugin on new Hermes, bundled one on older.
if [ -n "${HERMES_LANGFUSE_PUBLIC_KEY:-}" ]; then
  hermes plugins enable langfuse 2>/dev/null || hermes plugins install langfuse --enable 2>/dev/null \
    || hermes plugins enable observability/langfuse || echo "WARN: Langfuse plugin not enabled"
fi

python3 - <<'EOF'
import glob, json, subprocess
existing = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True).stdout
for f in sorted(glob.glob("/opt/noc-engineer/cron/*.json")):
    j = json.load(open(f))
    if j["name"] in existing:
        continue
    cmd = ["hermes", "cron", "create", j["schedule"], j["prompt"], "--name", j["name"], "--deliver", j["deliver"]]
    for s in j.get("skills", []):
        cmd += ["--skill", s]
    if j.get("script"):
        cmd += ["--script", j["script"]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(("scheduled " if r.returncode == 0 else "FAILED ") + j["name"], r.stderr.strip()[:200])
EOF

# Settings `hermes cron create` has no flag for (attach_to_session, failure_deliver).
python3 "$SRC/cron_settings.py" "$SRC/cron" || echo "WARN: cron settings not fully applied (see above)"

exec hermes gateway run
