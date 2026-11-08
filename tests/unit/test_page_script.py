"""The web page script parses. One syntax error stops the whole page (seen once: a quote in a string)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path("frontend/index.html")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is in the pipeline image; not on this machine")
def test_inline_script_has_no_syntax_error(tmp_path):
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", PAGE.read_text(), re.S)
    assert blocks, "no inline script found"
    for i, js in enumerate(blocks):
        f = tmp_path / f"page_{i}.js"
        f.write_text(js)
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-800:]
