"""docs/LLD.md and the real API must list the same endpoints (loose coupling: the page knows only these)."""

import re
from pathlib import Path

from optpred.serving.signal_api import Settings, create_app

LLD = Path(__file__).resolve().parents[2] / "docs" / "LLD.md"
SKIP = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def test_lld_lists_every_route_and_nothing_else():
    app = create_app(Settings(), model=object(), client=object())
    real = {
        (m, r.path) for r in app.routes if hasattr(r, "methods") and r.path not in SKIP for m in r.methods
    }
    documented = set(re.findall(r"^### (GET|POST) (\S+)$", LLD.read_text(), re.M))
    assert documented == real


def test_web_page_calls_only_documented_paths():
    page = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text()
    called = {p.split("?")[0] for p in re.findall(r'api\(\s*[`"](/[a-z/]+)', page)}
    documented = {p for _, p in re.findall(r"^### (GET|POST) (\S+)$", LLD.read_text(), re.M)}
    assert called and called <= documented | {"/pipeline/runs/"}
