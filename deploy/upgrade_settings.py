#!/usr/bin/env python3
"""Keep our Hermes settings across upgrades.

  upgrade_settings.py snapshot              copy config.yaml + versions to $HERMES_HOME/backups/settings-<ts>/
  upgrade_settings.py check                 compare config.yaml + env with deploy/settings-lock.yaml and with the
                                            installed Hermes defaults; exit 1 on a required failure
  upgrade_settings.py apply [--recommended] set missing/mismatched values with `hermes config set`
                                            (Hermes validates each key); owner_decision items are never applied
  upgrade_settings.py diff-defaults OLD.json NEW.json
                                            list config keys added/removed between two Hermes versions
                                            (dump with: python3 -c "import json,hermes_cli.config_defaults as c;
                                            print(json.dumps(c.DEFAULT_CONFIG, default=str))")

Run inside the Hermes container (it imports hermes_cli to read the installed defaults).
Never prints secret values.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
LOCK = Path(os.environ.get("NOC_SETTINGS_LOCK", HERE / "settings-lock.yaml"))
HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CONFIG = Path(os.environ.get("HERMES_CONFIG", HOME / "config.yaml"))

# Keys read by the gateway or model layer that DEFAULT_CONFIG does not seed.
EXTRA_KNOWN_PREFIXES = ("group_sessions_per_user", "thread_sessions_per_user", "model.", "streaming.",
                        "display.platforms.", "fallback_providers", "custom_providers", "mcp_servers")
# Free-form subtrees: their children are user data, not schema keys.
FREEFORM = ("approvals.deny", "display.platforms", "monitoring.export.otlp.headers_env", "custom_providers",
            "fallback_providers", "agent.reasoning_overrides", "mcp_servers", "model", "skills.config")

MISSING = object()


def get(d, key):
    for part in key.split("."):
        if not isinstance(d, dict) or part not in d:
            return MISSING
        d = d[part]
    return d


def flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        kk = f"{prefix}{k}"
        if any(kk == f or kk.startswith(f + ".") for f in FREEFORM):
            out[kk] = v
        elif isinstance(v, dict) and v:
            out.update(flat(v, kk + "."))
        else:
            out[kk] = v
    return out


def load_defaults():
    try:
        import hermes_cli.config_defaults as c  # noqa: PLC0415
        return c.DEFAULT_CONFIG
    except Exception as e:  # noqa: BLE001
        print(f"WARN  cannot import hermes_cli.config_defaults ({e}); key-existence checks skipped")
        return None


def hermes_version():
    try:
        r = subprocess.run(["hermes", "--version"], capture_output=True, text=True, timeout=30)
        return (r.stdout or r.stderr).strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001
        return f"unknown ({e})"


def known(key, defaults):
    if defaults is None:
        return True
    if any(key == p.rstrip(".") or key.startswith(p) for p in EXTRA_KNOWN_PREFIXES):
        return True
    return get(defaults, key) is not MISSING


def evaluate(item, cfg, defaults):
    key, kind = item["key"], item.get("kind", "config")
    check = item.get("check", "equals")
    if kind == "env":
        cur = os.environ.get(key)
        if check == "present":
            return ("OK" if cur else "MISSING"), "set" if cur else "not set"
        ok = cur == str(item["value"])
        return ("OK" if ok else "MISMATCH"), f"is {'expected' if ok else 'different/unset'}"
    if not known(key, defaults):
        return "UNKNOWN_KEY", "not in this Hermes version's defaults: renamed/removed? verify in source"
    cur = get(cfg, key)
    if check == "nonempty":
        return ("OK" if cur not in (MISSING, None, "", [], {}) else "MISSING"), "has value" if cur not in (MISSING, None, "", [], {}) else "empty"
    if cur is MISSING:
        return "MISSING", f"want {item['value']!r}"
    return ("OK" if cur == item["value"] else "MISMATCH"), f"is {cur!r}, want {item['value']!r}"


def cmd_check(args):
    lock = yaml.safe_load(LOCK.read_text())["settings"]
    cfg = yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}
    defaults = load_defaults()
    print(f"hermes: {hermes_version()}  config: {CONFIG}  lock: {LOCK}")
    if defaults is not None:
        print(f"config schema version (defaults): {defaults.get('_config_version')}")
    failed = 0
    for item in lock:
        state, detail = evaluate(item, cfg, defaults)
        st = item.get("status", "required")
        if state != "OK" and st == "required":
            failed += 1
        print(f"{state:12} {st:15} {item['key']:58} {detail}")
    if defaults is not None:
        dflat = flat(defaults)
        unknown = [k for k in flat(cfg) if not known(k, defaults) and k not in dflat]
        for k in unknown:
            print(f"{'STALE?':12} {'-':15} {k:58} in config.yaml but not in defaults: run `hermes config check`")
    print(f"\nrequired failures: {failed}")
    return 1 if failed else 0


def cmd_apply(args):
    lock = yaml.safe_load(LOCK.read_text())["settings"]
    cfg = yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}
    defaults = load_defaults()
    cmd_snapshot(args)
    todo = []
    for item in lock:
        st = item.get("status", "required")
        if st == "owner_decision" or item.get("kind", "config") == "env" or "value" not in item:
            continue
        if st == "recommended" and not args.recommended:
            continue
        state, _ = evaluate(item, cfg, defaults)
        if state in ("MISSING", "MISMATCH"):
            todo.append(item)
        elif state == "UNKNOWN_KEY":
            print(f"SKIP  {item['key']}: unknown in this version, fix the lock file first")
    for item in todo:
        val = json.dumps(item["value"]) if not isinstance(item["value"], str) else item["value"]
        r = subprocess.run(["hermes", "config", "set", item["key"], val], capture_output=True, text=True)
        print(f"{'SET ' if r.returncode == 0 else 'FAIL'}  {item['key']} = {val}  {(r.stderr or '').strip()[:200]}")
    print("env and owner_decision items are not changed here; set env in the k8s Secret/manifest.")
    return cmd_check(args)


def cmd_snapshot(args):
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HOME / "backups" / f"settings-{ts}"
    out.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        shutil.copy2(CONFIG, out / "config.yaml")
    shutil.copy2(LOCK, out / "settings-lock.yaml")
    (out / "VERSION").write_text(hermes_version() + "\n")
    print(f"snapshot: {out}")
    return 0


def cmd_diff(args):
    a, b = json.loads(Path(args.old).read_text()), json.loads(Path(args.new).read_text())
    fa, fb = flat(a), flat(b)
    print(f"schema {a.get('_config_version')} -> {b.get('_config_version')}")
    for k in sorted(set(fa) - set(fb)):
        print(f"REMOVED  {k}")
    for k in sorted(set(fb) - set(fa)):
        print(f"ADDED    {k} = {str(fb[k])[:80]}")
    for k in sorted(set(fa) & set(fb)):
        if fa[k] != fb[k]:
            print(f"DEFAULT  {k}: {str(fa[k])[:40]} -> {str(fb[k])[:40]}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    a = sub.add_parser("apply")
    a.add_argument("--recommended", action="store_true")
    sub.add_parser("snapshot")
    d = sub.add_parser("diff-defaults")
    d.add_argument("old")
    d.add_argument("new")
    args = p.parse_args()
    return {"check": cmd_check, "apply": cmd_apply, "snapshot": cmd_snapshot, "diff-defaults": cmd_diff}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
