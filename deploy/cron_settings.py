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
