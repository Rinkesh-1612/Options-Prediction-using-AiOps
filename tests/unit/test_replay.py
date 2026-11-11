"""The demo replay (scripts/replay.py) calls /signal and /vol for every step of every day of the split."""

import importlib.util
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location("replay", Path("scripts/replay.py"))
replay_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_mod)


def test_replay_counts_answers_and_refusals():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/days":
            return httpx.Response(200, json=[{"day": "d1", "split": "test"}, {"day": "d0", "split": "dev"}])
        seen.append((req.url.path, req.url.params["day"]))
        return httpx.Response(200 if req.url.path == "/signal" else 503, json={})

    c = httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    n = replay_mod.replay("http://api", "test", 0.0, 7200, client=c)
    steps = len(range(replay_mod.FIRST_S, replay_mod.LAST_S + 1, 7200))
    assert n == {"days": 1, "ok": steps, "refused": steps}
    assert {d for _, d in seen} == {"d1"}  # dev days are not replayed
