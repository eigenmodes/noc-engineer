import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import e2e_check as e  # noqa: E402


@pytest.fixture
def ctx(env, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    monkeypatch.setattr(e, "HOME", home)
    monkeypatch.setattr(e, "SRC", ROOT)
    e.RESULTS.clear()
    return home


def last():
    return e.RESULTS[-1]


CFG = {"model": {"default": "kimi-k3", "base_url": "http://llm/v1"}, "group_sessions_per_user": False,
       "cron": {"mirror_delivery": True}}


def test_tool_calling_pass_and_fail(ctx, fake):
    reply = {"choices": [{"message": {"tool_calls": [{"function": {"name": "ping", "arguments": "{}"}}]}}]}
    fake({"/chat/completions": lambda *a: reply})
    e.c_model_tools(CFG)
    assert last()["status"] == "PASS"
    fake({"/chat/completions": lambda *a: {"choices": [{"message": {"content": "pong"}}]}})
    e.c_model_tools(CFG)
    assert last()["status"] == "FAIL" and "no tool_calls" in last()["detail"]


def test_model_not_served(ctx, fake):
    fake({"/models": lambda *a: {"data": [{"id": "other"}]}})
    e.c_model_up(CFG)
    assert last()["status"] == "FAIL" and "kimi-k3" in last()["detail"]


def test_sessions_defaults_fail(ctx, monkeypatch):
    monkeypatch.setenv("MATTERMOST_REPLY_MODE", "thread")
    e.c_sessions({"session_reset": {"mode": "daily"}})
    d = last()["detail"]
    assert last()["status"] == "FAIL" and "group_sessions_per_user" in d and "session_reset" in d and "thread" in d
    e.c_sessions(CFG)
    monkeypatch.delenv("MATTERMOST_REPLY_MODE")
    e.c_sessions(CFG)
    assert last()["status"] == "PASS"


def test_allowed_users_must_be_ids(ctx, fake, monkeypatch):
    monkeypatch.setenv("MATTERMOST_URL", "http://mm")
    monkeypatch.setenv("MATTERMOST_ALLOWED_USERS", "nir.alon")
    e.c_mm_users()
    assert last()["status"] == "FAIL" and "26-char" in last()["detail"]
    uid = "a" * 26
    monkeypatch.setenv("MATTERMOST_ALLOWED_USERS", uid)
    fake({"/users/ids": lambda *a: [{"id": uid}]})
    e.c_mm_users()
    assert last()["status"] == "PASS"


def test_cron_checks(ctx):
    specs = {j["name"]: j for j in e._specs()}
    live = {name: {"id": f"id-{name}", "name": name, "enabled": True, "deliver": s["deliver"],
                   "attach_to_session": s.get("attach_to_session")} for name, s in specs.items()}
    e.c_cron_jobs(live)
    assert last()["status"] == "PASS"
    live["daily-summary"]["enabled"] = False
    e.c_cron_jobs(live)
    assert last()["status"] == "FAIL" and "daily-summary: paused" in last()["detail"]
    e.c_cron_settings(live)
    assert last()["status"] == "PASS"
    live["anomaly-scan"]["attach_to_session"] = None
    e.c_cron_settings(live)
    assert last()["status"] == "FAIL"
    # recent runs: anomaly-scan ran long ago -> stale
    out = ctx / "cron" / "output" / "id-anomaly-scan"
    out.mkdir(parents=True)
    f = out / "old.md"
    f.write_text("ok")
    old = time.time() - 6 * 3600
    os.utime(f, (old, old))
    e.c_cron_runs(live)
    assert last()["status"] == "FAIL" and "anomaly-scan: last run" in last()["detail"]


def test_main_exit_code_on_missing_env(ctx, fake, monkeypatch, capsys):
    for k in ("OPENAI_API_KEY", "MATTERMOST_URL", "MATTERMOST_TOKEN", "PROMETHEUS_URL"):
        monkeypatch.delenv(k, raising=False)
    fake({"/api/v1/query": lambda *a: {"status": "success", "data": {"result": []}},
          "/alerts": lambda *a: [], "/search": lambda *a: {"issues": []},
          "/_cluster/health": lambda *a: {"status": "green"}})
    monkeypatch.setattr(e, "_live_jobs", lambda: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(e.shutil, "which", lambda *_: None)
    code = e.main(["--json"])
    res = {r["id"]: r for r in json.loads(capsys.readouterr().out)}
    assert code == 2 and res["env.required"]["status"] == "FAIL"
    assert res["backend.prometheus"]["status"] == "PASS"


def test_langfuse_check(ctx, fake, monkeypatch):
    monkeypatch.delenv("HERMES_LANGFUSE_PUBLIC_KEY", raising=False)
    e.c_langfuse()
    assert last()["status"] == "SKIP"
    monkeypatch.setenv("HERMES_LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("HERMES_LANGFUSE_SECRET_KEY", "sk-lf-x")
    monkeypatch.setenv("HERMES_LANGFUSE_BASE_URL", "http://lf")
    monkeypatch.setattr(e.shutil, "which", lambda *_: None)
    fake({"/api/public/health": lambda *a: {"status": "OK"}, "/api/public/projects": lambda *a: {"data": []}})
    e.c_langfuse()
    assert last()["status"] == "PASS"
