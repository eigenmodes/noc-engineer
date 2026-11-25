#!/usr/bin/env python3
"""Configure the Langfuse project for the NOC agent. Idempotent: creates only what is missing.

  LANGFUSE_URL=https://langfuse.internal LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-... \
  python3 bootstrap.py [--model deepseek-v4] [--input-price 0] [--output-price 0] [--dry-run]

Creates (Langfuse public API, Basic auth with the project keys):
  1. a model definition, so token usage of the internal model is priced (USD per token; 0 = count only)
  2. score configs used to grade the agent (manually in the UI or by the eval run)
Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

SCORE_CONFIGS = [
    {"name": "located_hop", "dataType": "BOOLEAN",
     "description": "The answer names the correct hop / component where the problem is."},
    {"name": "root_cause", "dataType": "CATEGORICAL",
     "categories": [{"label": "wrong", "value": 0}, {"label": "partial", "value": 1}, {"label": "correct", "value": 2}],
     "description": "Root cause compared with the known resolution of the incident or ticket."},
    {"name": "evidence_cited", "dataType": "BOOLEAN",
     "description": "Every finding cites its query, time window and value."},
    {"name": "invented_values", "dataType": "BOOLEAN",
     "description": "True if the answer states a value, host or metric that no tool returned (hallucination)."},
    {"name": "customer_safe", "dataType": "BOOLEAN",
     "description": "A customer-facing answer reveals nothing about other customers or internal findings."},
    {"name": "user_feedback", "dataType": "CATEGORICAL",
     "categories": [{"label": "bad", "value": 0}, {"label": "ok", "value": 1}, {"label": "good", "value": 2}],
     "description": "Team member's rating of the answer."},
]


class Api:
    def __init__(self, url: str, pk: str, sk: str, dry: bool):
        self.base = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()
        self.dry = dry

    def call(self, method: str, path: str, body=None):
        if self.dry and method != "GET":
            print(f"DRY {method} {path} {json.dumps(body)[:160]}")
            return {}
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} -> {e.code}: {e.read(300).decode(errors='replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"cannot reach {self.base}: {e.reason}")
        return json.loads(raw) if raw else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("NOC_MODEL", "deepseek-v4"),
                    help="model id exactly as Hermes sends it (config.yaml model.default)")
    ap.add_argument("--input-price", type=float, default=0.0, help="USD per input token (0 = count only)")
    ap.add_argument("--output-price", type=float, default=0.0, help="USD per output token")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    missing = [v for v in ("LANGFUSE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.environ.get(v)]
    if missing:
        sys.exit("set " + ", ".join(missing))
    api = Api(os.environ["LANGFUSE_URL"], os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"], a.dry_run)

    api.call("GET", "/api/public/health")
    api.call("GET", "/api/public/projects")          # 401 here = wrong project keys
    print("OK   Langfuse reachable, keys accepted")

    models = api.call("GET", "/api/public/models?limit=100").get("data", [])
    if any(m.get("modelName") == a.model and not m.get("isLangfuseManaged") for m in models):
        print(f"SKIP model {a.model} (exists)")
    else:
        api.call("POST", "/api/public/models", {
            "modelName": a.model, "matchPattern": f"(?i)^{a.model}$", "unit": "TOKENS",
            "inputPrice": a.input_price, "outputPrice": a.output_price})
        print(f"ADD  model {a.model} (input {a.input_price} / output {a.output_price} USD per token)")

    have = {c.get("name") for c in api.call("GET", "/api/public/score-configs?limit=100").get("data", [])}
    for cfg in SCORE_CONFIGS:
        if cfg["name"] in have:
            print(f"SKIP score config {cfg['name']} (exists)")
        else:
            api.call("POST", "/api/public/score-configs", cfg)
            print(f"ADD  score config {cfg['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
