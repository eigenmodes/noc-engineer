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

# Langfuse tracing only when its keys are in the Secret. The plugin is installed once into HERMES_HOME (PVC).
# LANGFUSE_PLUGIN_SOURCE: internal mirror of hermes-official-plugins, e.g. https://git.internal/x/hermes-official-plugins.git#langfuse
# (empty = public catalog, needs internet). The SDK is already in the image, so the dependency step needs no network.
if [ -n "${HERMES_LANGFUSE_PUBLIC_KEY:-}" ]; then
  if hermes plugins list 2>/dev/null | grep -qw langfuse; then
    hermes plugins enable langfuse >/dev/null 2>&1 || true
  else
    hermes plugins install "${LANGFUSE_PLUGIN_SOURCE:-langfuse}" --yes-deps --enable \
      || { hermes plugins install "${LANGFUSE_PLUGIN_SOURCE:-langfuse}" --no-deps && hermes plugins enable langfuse; } \
      || echo "WARN: Langfuse plugin not installed (see code-review/LANGFUSE.md, troubleshooting)"
  fi
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
