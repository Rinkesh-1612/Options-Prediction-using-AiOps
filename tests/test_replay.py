"""Replay talks to the API only over REST; here the API is a fake transport."""

import httpx
import pytest

from optpred import replay


def fake_api(days, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/days":
            return httpx.Response(200, json=days)
        if req.url.path == "/minutes":
            return httpx.Response(200, json=[{"minute": 600, "time": "10:00"}, {"minute": 601, "time": "10:01"}])
        calls.append(req.read())
        return httpx.Response(200, json={})

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


DAYS = [{"day": "2026-09-01", "split": "train"}, {"day": "2026-09-25", "split": "val"}, {"day": "2026-09-30", "split": "val"}]


def test_default_day_is_the_latest_validation_day():
    assert replay.pick_day(DAYS, None) == "2026-09-30"


def test_unknown_day_is_refused():
    with pytest.raises(replay.ReplayError):
        replay.pick_day(DAYS, "2026-10-10")


def test_every_minute_is_sent_once_per_loop():
    calls = []
    n = replay.replay("http://api", None, 0.0, 2, client=fake_api(DAYS, calls))
    assert n == 4 and len(calls) == 4 and b"2026-09-30" in calls[0]


def test_an_unreachable_api_gives_a_clear_error():
    def boom(req):
        raise httpx.ConnectError("refused")

    c = httpx.Client(base_url="http://api", transport=httpx.MockTransport(boom))
    with pytest.raises(replay.ReplayError):
        replay.replay("http://api", None, 0.0, 1, client=c)


def test_a_split_is_replayed_day_by_day():
    calls = []
    n = replay.replay("http://api", None, 0.0, 1, client=fake_api(DAYS, calls), split="val")
    assert n == 4 and b"2026-09-25" in calls[0] and b"2026-09-30" in calls[2]  # two val days, in order
