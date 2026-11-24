import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
import run_evals  # noqa: E402


def test_score_heuristics():
    case = yaml.safe_load((ROOT / "evals" / "cases.example.yaml").read_text())[0]
    good = "Bottom line: Kafka hop. Consumer lag after a rebalance. Query: sum by (group) (rate(lag[5m])) from 14:05."
    s = run_evals.score(case, good)
    assert s["pass"] and s["located_hop"] and s["root_cause"] == "correct" and s["evidence_cited"]
    s = run_evals.score(case, "Probably the rule config. Consumer lag maybe.")
    assert not s["pass"] and s["root_cause"] == "partial" and s["located_hop"] is False
    s = run_evals.score({**case, "forbid": ["customer-b"]}, good + " Customer-B also affected.")
    assert not s["pass"] and s["forbidden_found"] == ["customer-b"]


def test_main_with_fake_agent(monkeypatch, tmp_path, capsys):
    cases = tmp_path / "cases.yaml"
    cases.write_text((ROOT / "evals" / "cases.example.yaml").read_text())
    monkeypatch.setattr(run_evals, "ask", lambda q, t: ("Kafka: consumer lag after rebalance, rate(x[5m])", 1.0, 0))
    assert run_evals.main([str(cases)]) == 0
    assert "1/1 passed" in capsys.readouterr().out
