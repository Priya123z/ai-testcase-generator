"""The browser demo reimplements two serialisers in JavaScript.

site/app.js has its own toGherkin and toPytest because the page has no Python to
call — it talks to Groq directly from the visitor's browser. That is real
duplication, so this pins it: both implementations must produce byte-identical
output for the same suite. Skipped when node is not installed, so a clean clone
still passes.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.generator import suite_to_gherkin, suite_to_pytest
from app.models import TestSuite

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "site" / "app.js"
SAMPLE = ROOT / "site" / "samples" / "login.json"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(fn: str, payload: dict) -> str:
    """Pull the two serialisers out of app.js and run them without a DOM."""
    src = APP_JS.read_text()
    start = src.index("// Mirrors suite_to_gherkin")
    end = src.index("const $ = id =>")

    script = (
        src[start:end]
        + f"\nconst suite = JSON.parse(process.argv[1]);"
        + f"\nprocess.stdout.write({fn}(suite));"
    )
    out = subprocess.run(
        ["node", "-e", script, json.dumps(payload)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE.read_text())


def test_saved_answer_is_a_valid_suite(sample):
    # The no-key path is what most visitors see. If this file drifts from the
    # model the page expects, the demo silently renders nothing.
    suite = TestSuite(**sample)
    assert suite.feature
    assert suite.scenarios
    assert suite.pytest_cases


@needs_node
def test_gherkin_matches_python(sample):
    assert run_js("toGherkin", sample) == suite_to_gherkin(TestSuite(**sample))


@needs_node
def test_pytest_matches_python(sample):
    assert run_js("toPytest", sample) == suite_to_pytest(TestSuite(**sample))
