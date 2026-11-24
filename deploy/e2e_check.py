#!/usr/bin/env python3
"""End-to-end health check of the running NOC agent. Run inside the pod:

  python3 /opt/noc-engineer/e2e_check.py                 # all checks, read-only
  python3 /opt/noc-engineer/e2e_check.py --json          # machine-readable
  python3 /opt/noc-engineer/e2e_check.py --run-job anomaly-scan [--timeout 300]
        # also triggers that cron job and waits for a new run file in cron/output/<id>/
        # (a job with findings posts to the channel, like a normal run)

Exit code: 2 = a P0 check failed, 1 = a P1 check failed, 0 = otherwise.
Read-only except the model test call (a few tokens) and --run-job. Never prints secrets.
What each check means and how to fix it: guides/E2E-CHECKS.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(os.environ.get("NOC_SRC", Path(__file__).resolve().parent))   # /opt/noc-engineer in the image
HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _hermes_python():
    exe = shutil.which("hermes")
    if not exe:
        return None
    with open(exe, "rb") as f:
        first = f.readline().decode(errors="ignore")
    parts = first[2:].split() if first.startswith("#!") else []
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
    return shutil.which(parts[0]) if parts and "python" in parts[0] else None


if __name__ == "__main__":
    try:
        import cron.jobs  # noqa: F401  (Hermes' own module: present only under Hermes' Python)
    except ImportError:
        py = _hermes_python()
        if py and not os.environ.get("_E2E_REEXEC"):
            os.environ["_E2E_REEXEC"] = "1"
            os.execv(py, [py, *sys.argv])

for p in (HOME / "skills" / "noc-tools" / "scripts", SRC / "skills" / "noc-tools" / "scripts",
          SRC.parent / "skills" / "noc-tools" / "scripts"):
    if p.is_dir():
        sys.path.insert(0, str(p))
        break
import noclib as n  # noqa: E402
import yaml  # noqa: E402

RESULTS: list[dict] = []


def record(cid, sev, status, detail=""):
    RESULTS.append({"id": cid, "sev": sev, "status": status, "detail": str(detail)[:300]})


def check(cid, sev):
    """Decorator: a check returns (status, detail); an exception is a FAIL with its message."""
    def wrap(fn):
        def run(*a, **k):
            try:
                status, detail = fn(*a, **k)
            except n.NocError as e:
                status, detail = "FAIL", f"{e.code}: {e.message}"
            except Exception as e:  # noqa: BLE001
                status, detail = "FAIL", f"{type(e).__name__}: {e}"
            record(cid, sev, status, detail)
            return status
        run.cid = cid
        return run
    return wrap


def _yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def _tbd(v) -> bool:
    return v in (None, "") or "REPLACE" in str(v) or n.is_tbd(v)


# ---------------- configuration ----------------

@check("env.required", "P0")
def c_env():
    dist = _yaml(SRC / "distribution.yaml") or _yaml(HOME / "distribution.yaml")
    missing = [e["name"] for e in dist.get("env_requires", []) if e.get("required") and not os.environ.get(e["name"])]
    return ("FAIL", "missing: " + ", ".join(missing)) if missing else ("PASS", "all required env vars set")


@check("home.writable", "P0")
def c_home():
    probe = HOME / ".e2e_probe"
    probe.write_text("ok")
    probe.unlink()
    return "PASS", str(HOME)


@check("config.model", "P0")
def c_model_cfg(cfg):
    m = cfg.get("model") or {}
    bad = [k for k in ("base_url", "default") if _tbd(m.get(k))]
    return ("FAIL", f"model.{', model.'.join(bad)} not filled") if bad else ("PASS", f"{m['default']} @ {m['base_url']}")


@check("config.sessions", "P1")
def c_sessions(cfg):
    problems = []
    if cfg.get("group_sessions_per_user") is not False:
        problems.append("group_sessions_per_user is not false (default true)")
    if "session_reset" in cfg:
        problems.append("session_reset is set but does not exist in v0.22.5")
    if os.environ.get("MATTERMOST_REPLY_MODE", "off").lower() == "thread":
        problems.append("MATTERMOST_REPLY_MODE=thread")
    if not (cfg.get("cron") or {}).get("mirror_delivery"):
        problems.append("cron.mirror_delivery not true (P2: mirror is best effort)")
    return ("FAIL", "; ".join(problems)) if problems else ("PASS", "shared channel session, reply in channel, mirror on")


@check("skills.installed", "P0")
def c_skills():
    want = sorted(p.parent.name for p in (SRC / "skills").glob("*/SKILL.md"))
    missing = [s for s in want if not (HOME / "skills" / s / "SKILL.md").exists()]
    return ("FAIL", "missing in HERMES_HOME: " + ", ".join(missing)) if missing else ("PASS", f"{len(want)} skills")


# ---------------- model endpoint ----------------

def _model_req(cfg, method, path, body=None):
    m = cfg["model"]
    return n.HTTP.request(method, m["base_url"].rstrip("/") + path, body=body,
                          headers=n.bearer(os.environ.get("OPENAI_API_KEY")))


@check("model.reachable", "P0")
def c_model_up(cfg):
    body = _model_req(cfg, "GET", "/models")
    ids = [x.get("id") for x in (body or {}).get("data", [])] if isinstance(body, dict) else []
    want = cfg["model"]["default"]
    if ids and want not in ids:
        return "FAIL", f"model '{want}' not served; endpoint lists: {', '.join(ids[:8])}"
    return "PASS", f"{len(ids)} models listed" + ("" if ids else " (endpoint returned no list)")


@check("model.tool_calling", "P0")
def c_model_tools(cfg):
    body = _model_req(cfg, "POST", "/chat/completions", {
        "model": cfg["model"]["default"], "max_tokens": 64, "temperature": 0,
        "messages": [{"role": "user", "content": "Call the ping tool with text 'e2e'. Do not answer in text."}],
        "tools": [{"type": "function", "function": {
            "name": "ping", "description": "health check",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}],
        "tool_choice": "auto"})
    msg = ((body or {}).get("choices") or [{}])[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    if calls and calls[0].get("function", {}).get("name") == "ping":
        return "PASS", "endpoint returns OpenAI-style tool_calls"
    return "FAIL", "no tool_calls in the reply: the agent cannot run tools (answers from memory). Reply: " + \
        str(msg.get("content"))[:120]


# ---------------- Mattermost ----------------

def _mm(method, path, body=None):
    url = os.environ["MATTERMOST_URL"].rstrip("/") + "/api/v4" + path
    return n.HTTP.request(method, url, body=body, headers=n.bearer(os.environ.get("MATTERMOST_TOKEN")))


@check("mattermost.bot", "P0")
def c_mm_bot():
    me = _mm("GET", "/users/me")
    return "PASS", f"token valid: @{me.get('username')} (is_bot={me.get('is_bot')})"


@check("mattermost.home_channel", "P0")
def c_mm_home():
    cid = os.environ.get("MATTERMOST_HOME_CHANNEL", "")
    ch = _mm("GET", f"/channels/{cid}")
    _mm("GET", f"/channels/{cid}/members/me")          # 404 -> bot is not a member: cron posts would fail
    return "PASS", f"bot is a member of ~{ch.get('name')}"


@check("mattermost.allowed_users", "P1")
def c_mm_users():
    ids = [u.strip() for u in os.environ.get("MATTERMOST_ALLOWED_USERS", "").split(",") if u.strip()]
    if not ids:
        return "FAIL", "MATTERMOST_ALLOWED_USERS empty: nobody can talk to the agent"
    bad = [u for u in ids if not re.fullmatch(r"[a-z0-9]{26}", u)]
    if bad:
        return "FAIL", f"not 26-char user IDs (usernames?): {', '.join(bad)}"
    found = {u.get("id") for u in (_mm("POST", "/users/ids", ids) or [])}
    unknown = [u for u in ids if u not in found]
    return ("FAIL", "unknown IDs: " + ", ".join(unknown)) if unknown else ("PASS", f"{len(ids)} users exist")


# ---------------- data backends (via noc-tools config) ----------------

@check("backend.prometheus", "P0")
def c_prom():
    if _tbd(n.section("prometheus").get("url")):
        return "FAIL", "PROMETHEUS_URL not set: anomaly scan and investigations cannot run"
    n.prom_instant("vector(1)")
    return "PASS", "query API answers"


@check("backend.grafana", "P1")
def c_grafana():
    if _tbd(n.section("grafana").get("url")):
        return "SKIP", "not configured"
    return "PASS", f"{len(n.grafana_alerts())} active alerts readable"


@check("backend.jira", "P1")
def c_jira():
    j = n.section("jira")
    if _tbd(j.get("url")):
        return "SKIP", "not configured"
    if _tbd(j.get("customer_jql")):
        return "FAIL", "jira.customer_jql is TBD: ticket polling does nothing"
    n.jira_search(f"({j['customer_jql']}) AND updated >= -1d", 1, "summary")
    return "PASS", "customer JQL accepted"


@check("backend.elasticsearch", "P1")
def c_es():
    es = n.section("elasticsearch")
    if _tbd(es.get("url")):
        return "SKIP", "not configured"
    h = n.basic(es["user"], es.get("password", "")) if not _tbd(es.get("user")) else {}
    body = n.HTTP.request("GET", es["url"].rstrip("/") + "/_cluster/health", headers=h)
    status = (body or {}).get("status")
    if _tbd(es.get("default_index")):
        return "FAIL", f"cluster {status}, but elasticsearch.default_index is TBD"
    return ("PASS" if status in ("green", "yellow") else "FAIL"), f"cluster status {status}"


@check("config.anomaly_checks", "P1")
def c_anomaly():
    checks = n.section("anomaly").get("checks") or []
    ok = [c for c in checks if not n.is_tbd(c.get("query"))]
    return ("PASS", f"{len(ok)} checks") if ok else ("FAIL", "no anomaly query configured: the 5-min scan does nothing")


# ---------------- cron ----------------

def _specs():
    return [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(SRC / "cron" / "*.json")))]


def _live_jobs():
    from cron import jobs as J
    return {j.get("name"): j for j in J.list_jobs(include_disabled=True)}


def _interval_minutes(schedule: str):
    m = re.fullmatch(r"\*/(\d+) \* \* \* \*", schedule.strip())
    if m:
        return int(m.group(1))
    if re.fullmatch(r"\d+ \d+ \* \* \*", schedule.strip()):
        return 24 * 60
    return None


@check("cron.jobs", "P0")
def c_cron_jobs(live):
    problems = []
    for s in _specs():
        j = live.get(s["name"])
        if j is None:
            problems.append(f"{s['name']}: not scheduled")
        elif j.get("enabled") is False or j.get("state") == "paused":
            problems.append(f"{s['name']}: paused")
        elif j.get("deliver") != s.get("deliver"):
            problems.append(f"{s['name']}: deliver={j.get('deliver')} (want {s.get('deliver')})")
    return ("FAIL", "; ".join(problems)) if problems else ("PASS", f"{len(live)} jobs, all enabled")


@check("cron.settings", "P2")
def c_cron_settings(live):
    diff = []
    for s in _specs():
        j = live.get(s["name"]) or {}
        for k in ("attach_to_session", "failure_deliver"):
            if k in s and j.get(k) != s[k]:
                diff.append(f"{s['name']}.{k}={j.get(k)!r}")
    return ("FAIL", "run cron_settings.py: " + ", ".join(diff)) if diff else ("PASS", "match cron/*.json")


@check("cron.recent_runs", "P1")
def c_cron_runs(live):
    stale, now = [], time.time()
    for s in _specs():
        j, every = live.get(s["name"]), _interval_minutes(s["schedule"])
        if not j or not every:
            continue
        files = sorted(glob.glob(str(HOME / "cron" / "output" / j["id"] / "*")), key=os.path.getmtime)
        if not files:
            stale.append(f"{s['name']}: no run yet")
            continue
        age = (now - os.path.getmtime(files[-1])) / 60
        if age > 3 * every + 5:
            stale.append(f"{s['name']}: last run {age:.0f} min ago (every {every})")
        elif "## Error" in Path(files[-1]).read_text(errors="replace"):
            stale.append(f"{s['name']}: last run has an error section")
    return ("FAIL", "; ".join(stale)) if stale else ("PASS", "every job ran on schedule, no error in last run")


def run_job(live, name, timeout):
    j = live.get(name)
    if not j:
        record("cron.run_job", "P1", "FAIL", f"no job named {name}")
        return
    out = HOME / "cron" / "output" / j["id"]
    before = set(glob.glob(str(out / "*")))
    subprocess.run(["hermes", "cron", "run", j["id"]], check=True, capture_output=True, timeout=60)
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = set(glob.glob(str(out / "*"))) - before
        if new:
            text = Path(sorted(new)[-1]).read_text(errors="replace")
            status = next((ln for ln in text.splitlines() if ln.startswith("**Status:**") or "wakeAgent=false" in ln),
                          "agent ran")
            record("cron.run_job", "P1", "FAIL" if "## Error" in text else "PASS", f"{name}: {status}")
            return
        time.sleep(5)
    record("cron.run_job", "P1", "FAIL", f"{name}: no new run file within {timeout}s (is the gateway running?)")


# ---------------- Langfuse ----------------

@check("langfuse.tracing", "P2")
def c_langfuse():
    pk, sk = os.environ.get("HERMES_LANGFUSE_PUBLIC_KEY"), os.environ.get("HERMES_LANGFUSE_SECRET_KEY")
    if not pk:
        return "SKIP", "HERMES_LANGFUSE_PUBLIC_KEY not set: tracing off"
    base = os.environ.get("HERMES_LANGFUSE_BASE_URL", "https://cloud.langfuse.com").rstrip("/")
    n.HTTP.request("GET", base + "/api/public/health")
    n.HTTP.request("GET", base + "/api/public/projects", headers=n.basic(pk, sk or ""))
    if shutil.which("hermes"):
        r = subprocess.run(["hermes", "plugins", "list"], capture_output=True, text=True, timeout=60)
        line = next((ln for ln in r.stdout.splitlines() if "langfuse" in ln), "")
        if not line:
            return "FAIL", "Langfuse reachable, but the langfuse plugin is not installed (LANGFUSE.md step 4)"
        return "PASS", f"{base} reachable, keys accepted; plugin: {' '.join(line.split())[:80]}"
    return "PASS", f"{base} reachable, keys accepted"


# ---------------- monitoring ----------------

@check("monitoring.status", "P2")
def c_monitoring():
    r = subprocess.run(["hermes", "monitoring", "status"], capture_output=True, text=True, timeout=60)
    first = ((r.stdout or r.stderr).strip().splitlines() or [""])[0]
    return ("PASS" if r.returncode == 0 else "FAIL"), first


@check("state.db_size", "P2")
def c_db():
    db = HOME / "state.db"
    if not db.exists():
        return "SKIP", "no state.db yet"
    mb = db.stat().st_size / 1e6
    return ("PASS" if mb < 2000 else "FAIL"), f"{mb:.0f} MB"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run-job")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)

    c_env()
    c_home()
    cfg = _yaml(HOME / "config.yaml")
    model_ok = c_model_cfg(cfg) == "PASS"
    c_sessions(cfg)
    c_skills()
    if model_ok:
        if c_model_up(cfg) == "PASS":
            c_model_tools(cfg)
    if os.environ.get("MATTERMOST_URL") and os.environ.get("MATTERMOST_TOKEN"):
        if c_mm_bot() == "PASS":
            c_mm_home()
            c_mm_users()
    for fn in (c_prom, c_grafana, c_jira, c_es, c_anomaly):
        fn()
    try:
        live = _live_jobs()
    except ImportError:
        record("cron.jobs", "P0", "SKIP", "Hermes cron module not importable (run inside the pod)")
        live = None
    if live is not None:
        c_cron_jobs(live)
        c_cron_settings(live)
        c_cron_runs(live)
        if a.run_job:
            run_job(live, a.run_job, a.timeout)
    c_langfuse()
    if shutil.which("hermes"):
        c_monitoring()
    c_db()

    if a.json:
        print(json.dumps(RESULTS, indent=1))
    else:
        for r in RESULTS:
            print(f"{r['status']:4}  {r['sev']}  {r['id']:26} {r['detail']}")
    failed = {r["sev"] for r in RESULTS if r["status"] == "FAIL"}
    return 2 if "P0" in failed else 1 if "P1" in failed else 0


if __name__ == "__main__":
    sys.exit(main())
