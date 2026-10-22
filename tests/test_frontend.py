"""The page and the API are loosely coupled: the page reaches the API only through config.json."""

import json
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[1] / "frontend"


def test_config_has_the_three_addresses():
    cfg = json.loads((FRONT / "config.json").read_text())
    assert set(cfg) == {"api_url", "mlflow_url", "grafana_url"}


def test_page_reads_the_api_address_from_config_not_from_code():
    html = (FRONT / "index.html").read_text()
    assert "config.json" in html and "cfg.api_url" in html
    assert not re.search(r"fetch\(['\"]https?://", html)  # no hard-coded backend address


def test_container_script_writes_the_same_keys():
    sh = (FRONT / "40-config.sh").read_text()
    for key in ("api_url", "mlflow_url", "grafana_url"):
        assert key in sh


def test_frontend_image_holds_no_python():
    assert "pip" not in (FRONT / "Dockerfile").read_text().replace("# Static web page only: no Python", "")


def test_every_backend_path_the_page_calls_is_in_the_low_level_design():
    html = (FRONT / "index.html").read_text()
    doc = (FRONT.parent / "docs/LLD.md").read_text()
    documented = [
        re.sub(r"\{[^}]+\}", "[^/]+", p) for p in re.findall(r"^### `(?:GET|POST) (/\S*)`", doc, re.M)
    ]
    called = {p for p in re.findall(r"api\([\"`](/[^\"`?$]*)", html) if not p.endswith("/")}
    called |= {p.split("/${")[0] + "/x/log" for p in re.findall(r"api\(`(/pipeline/runs/\$\{[^`]*)", html)}
    assert {"/results", "/predict", "/days"} <= called
    for path in called:
        assert any(re.fullmatch(d, path) for d in documented), path
