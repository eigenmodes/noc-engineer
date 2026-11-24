import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "langfuse"))
import bootstrap  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_bootstrap_is_idempotent(monkeypatch, capsys):
    store = {"models": [], "configs": [{"name": "located_hop"}]}
    posts = []

    def urlopen(req, timeout=0):
        path, body = req.full_url.split("http://lf", 1)[1], req.data and json.loads(req.data)
        assert req.headers["Authorization"].startswith("Basic ")
        if req.get_method() == "POST":
            posts.append((path, body))
            (store["models"] if "models" in path else store["configs"]).append(body)
            return Resp(b"{}")
        if path.startswith("/api/public/models"):
            return Resp(json.dumps({"data": store["models"]}).encode())
        if path.startswith("/api/public/score-configs"):
            return Resp(json.dumps({"data": store["configs"]}).encode())
        return Resp(b"{}")

    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", urlopen)
    for k, v in {"LANGFUSE_URL": "http://lf", "LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}.items():
        monkeypatch.setenv(k, v)
    assert bootstrap.main(["--model", "kimi-k3"]) == 0
    names = [b.get("name") or b.get("modelName") for _, b in posts]
    assert "kimi-k3" in names and "located_hop" not in names and "invented_values" in names
    model = next(b for p, b in posts if "models" in p)
    assert model["matchPattern"] == "(?i)^kimi-k3$" and model["unit"] == "TOKENS"
    posts.clear()
    assert bootstrap.main(["--model", "kimi-k3"]) == 0       # second run: nothing new
    assert posts == []
