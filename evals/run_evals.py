#!/usr/bin/env python3
"""Replay known incidents through the agent and score the answers. Run where `hermes` runs (the pod):

  python3 evals/run_evals.py evals/cases.yaml [--min-pass 0.8] [--only INC-1,INC-2] [--timeout 600]

Each case is sent as a fresh one-shot session: `hermes chat --oneshot -Q --source eval --query-file <q>`.
Automatic scores are heuristics (string checks); the final grade is human, in Langfuse, with the score
configs created by deploy/langfuse/bootstrap.py. Results: $HERMES_HOME/data/noc/evals/<UTC time>.jsonl (on the PVC; evals/results/ outside the pod).
Exit 1 if the pass rate is below --min-pass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import os
import tempfile
import time
from pathlib import Path

import yaml

EVIDENCE = re.compile(r"(sum by|rate\(|\[\d+[smhd]\]|promql|query|index|jql|from \d{1,2}:\d{2}|between \d{1,2}:\d{2})", re.I)


def ask(question: str, timeout: int) -> tuple[str, float, int]:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(question)
    t0 = time.time()
    r = subprocess.run(["hermes", "chat", "--oneshot", "-Q", "--source", "eval", "--query-file", f.name],
                       capture_output=True, text=True, timeout=timeout)
    Path(f.name).unlink(missing_ok=True)
    return (r.stdout or r.stderr).strip(), time.time() - t0, r.returncode


def score(case: dict, answer: str) -> dict:
    low = answer.lower()
    hops = [h.lower() for h in case.get("expect_hop", [])]
    causes = [c.lower() for c in case.get("expect_root_cause", [])]
    hit = sum(c in low for c in causes)
    forbidden = [w for w in case.get("forbid", []) if w.lower() in low]
    s = {
        "located_hop": any(h in low for h in hops) if hops else None,
        "root_cause": ("correct" if hit == len(causes) else "partial" if hit else "wrong") if causes else None,
        "evidence_cited": bool(EVIDENCE.search(answer)),
        "customer_safe": not forbidden,
        "forbidden_found": forbidden,
    }
    s["pass"] = (s["located_hop"] is not False) and s["root_cause"] != "wrong" and s["customer_safe"]
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--min-pass", type=float, default=0.8)
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    cases = yaml.safe_load(Path(a.cases).read_text()) or []
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    home = os.environ.get("HERMES_HOME")
    out_dir = Path(home) / "data" / "noc" / "evals" if home else Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".jsonl")
    rows = []
    for c in cases:
        try:
            answer, secs, rc = ask(c["question"], a.timeout)
        except subprocess.TimeoutExpired:
            answer, secs, rc = "", float(a.timeout), -1
        s = score(c, answer) if rc == 0 and answer else {"pass": False, "error": f"exit {rc}"}
        rec = {"id": c["id"], "kind": c.get("kind"), "audience": c.get("audience"), "seconds": round(secs, 1),
               "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **s, "answer": answer[:4000]}
        rows.append(rec)
        with out.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{'PASS' if rec['pass'] else 'FAIL'}  {c['id']:<18} hop={s.get('located_hop')} cause={s.get('root_cause')} "
              f"evidence={s.get('evidence_cited')} safe={s.get('customer_safe')} {secs:.0f}s {s.get('error', '')}")
    rate = sum(r["pass"] for r in rows) / len(rows) if rows else 0.0
    print(f"\n{sum(r['pass'] for r in rows)}/{len(rows)} passed ({rate:.0%}); results: {out}")
    print("Grade each trace in Langfuse (located_hop, root_cause, evidence_cited, invented_values, customer_safe).")
    return 0 if rate >= a.min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
