import importlib.util, os, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("us", ROOT / "deploy" / "upgrade_settings.py")
us = importlib.util.module_from_spec(spec); spec.loader.exec_module(us)


def test_lock_file_is_valid():
    items = yaml.safe_load((ROOT / "deploy" / "settings-lock.yaml").read_text())["settings"]
    assert items
    for it in items:
        assert it.get("status", "required") in ("required", "recommended", "owner_decision")
        assert it.get("check", "equals") in ("equals", "nonempty", "present")
        if it.get("check", "equals") == "equals":
            assert "value" in it, it["key"]


def test_group_sessions_lock_is_false():
    items = yaml.safe_load((ROOT / "deploy" / "settings-lock.yaml").read_text())["settings"]
    g = [i for i in items if i["key"] == "group_sessions_per_user"][0]
    assert g["value"] is False and g["status"] == "required"


def test_evaluate_states():
    cfg = {"cron": {"mirror_delivery": True}, "approvals": {"deny": []}}
    d = {"cron": {"mirror_delivery": False, "max_parallel_jobs": None}, "approvals": {"deny": []}}
    assert us.evaluate({"key": "cron.mirror_delivery", "value": True}, cfg, d)[0] == "OK"
    assert us.evaluate({"key": "cron.max_parallel_jobs", "value": 1}, cfg, d)[0] == "MISSING"
    assert us.evaluate({"key": "approvals.deny", "check": "nonempty"}, cfg, d)[0] == "MISSING"
    assert us.evaluate({"key": "nope.key", "value": 1}, cfg, d)[0] == "UNKNOWN_KEY"
    os.environ.pop("X_TEST_ENV", None)
    assert us.evaluate({"key": "X_TEST_ENV", "kind": "env", "check": "present"}, cfg, d)[0] == "MISSING"


def test_repo_config_passes_config_items():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    items = yaml.safe_load((ROOT / "deploy" / "settings-lock.yaml").read_text())["settings"]
    for it in items:
        if it.get("status", "required") == "required" and it.get("kind", "config") == "config":
            assert us.evaluate(it, cfg, None)[0] == "OK", it["key"]
