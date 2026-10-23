"""The serving image has no Spark. Anything the API or the model server imports must work without it."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module", ["optpred.serving.api", "optpred.serving.serving_model", "optpred.common.clock"]
)
def test_serving_code_imports_without_spark(module):
    code = "import sys; sys.modules['pyspark'] = None; sys.modules['pyspark.sql'] = None; " f"import {module}"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
