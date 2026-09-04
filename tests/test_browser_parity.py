"""The browser demo reimplements parts of the Python side in JavaScript.

site/app.js carries its own copy of the system prompt and its own toGherkin and
toPytest, because the page has no Python to call: it talks to Groq straight from
the visitor's browser. That duplication is real and unavoidable, so this module
pins it down.

The prompt test earns its place. The two copies had already drifted: the
JavaScript one was missing the clause telling the model to name what it chose
not to cover, so the same requirement produced measurably different output
depending on which path a visitor happened to take. Nothing caught it, because
nothing was comparing them.

The serialiser tests need node and are skipped without it, so a clean clone
still passes. The prompt test needs nothing and always runs.
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
        + "\nconst suite = JSON.parse(process.argv[1]);"
        + f"\nprocess.stdout.write({fn}(suite));"
    )
    out = subprocess.run(
        ["node", "-e", script, json.dumps(payload)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def js_prompt() -> str:
    """The system prompt as it is written in site/app.js."""
    src = APP_JS.read_text()
    return src.split("const SYSTEM_PROMPT = `", 1)[1].split("`;", 1)[0]


def test_prompt_matches_python():
    from app.prompts import SYSTEM_PROMPT_V1

    assert js_prompt() == SYSTEM_PROMPT_V1, (
        "site/app.js and app/prompts.py have drifted. Both paths must send the "
        "identical system prompt, or the same requirement produces different "
        "output depending on whether the visitor brought their own key."
    )


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
