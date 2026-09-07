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

The validator is pinned the same way, and by behaviour rather than by text:
feed both copies the same malformed suites and require them to agree on every
one. Comparing the source would not have caught the three shapes the JavaScript
used to wave through, because the two are not meant to read alike, only to
decide alike.

The tests that need node are skipped without it, so a clean clone still passes.
The prompt test needs nothing and always runs.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.generator import check_suite, suite_to_gherkin, suite_to_pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "site" / "app.js"
SAMPLE = ROOT / "site" / "samples" / "login.json"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(fn, payload):
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


def js_prompt():
    """The system prompt as it is written in site/app.js."""
    src = APP_JS.read_text()
    return src.split("const SYSTEM_PROMPT = `", 1)[1].split("`;", 1)[0]


def js_accepts(suite):
    """True if site/app.js's validate() accepts this suite."""
    src = APP_JS.read_text()
    start = src.index("function validate(s)")
    end = src.index("/* The line above every answer")

    script = (
        src[start:end]
        + "\ntry { validate(JSON.parse(process.argv[1])); process.stdout.write('ok'); }"
        + "\ncatch (e) { process.stdout.write('rejected'); }"
    )
    out = subprocess.run(
        ["node", "-e", script, json.dumps(suite)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout == "ok"


def python_accepts(suite):
    try:
        check_suite(copy.deepcopy(suite))
        return True
    except ValueError:
        return False


def broken(sample, mutate):
    suite = copy.deepcopy(sample)
    mutate(suite)
    return suite


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
    suite = check_suite(sample)
    assert suite["feature"]
    assert suite["scenarios"]
    assert suite["pytest_cases"]


@needs_node
def test_gherkin_matches_python(sample):
    assert run_js("toGherkin", sample) == suite_to_gherkin(check_suite(sample))


@needs_node
def test_pytest_matches_python(sample):
    assert run_js("toPytest", sample) == suite_to_pytest(check_suite(sample))


# Each of these is a shape a model has plausibly produced. Both copies of the
# validator have to make the same call on every one, or the same requirement
# gives one visitor a usable answer and another an error.
MALFORMED = {
    "no feature name": lambda s: s.update(feature=""),
    "no coverage notes": lambda s: s.update(coverage_notes=""),
    "coverage notes missing entirely": lambda s: s.pop("coverage_notes"),
    "no scenarios": lambda s: s.update(scenarios=[]),
    "an unnamed scenario": lambda s: s["scenarios"][0].update(name=""),
    "a step keyword that is not Gherkin": lambda s: s["scenarios"][0]["steps"][0].update(keyword="Whenever"),
    "a step with no text": lambda s: s["scenarios"][0]["steps"][0].update(text="  "),
    "no pytest cases": lambda s: s.update(pytest_cases=[]),
    "pytest cases missing entirely": lambda s: s.pop("pytest_cases"),
    "a name pytest will not collect": lambda s: s["pytest_cases"][0].update(function_name="CheckLogin"),
    "no docstring": lambda s: s["pytest_cases"][0].pop("docstring"),
    "a blank docstring": lambda s: s["pytest_cases"][0].update(docstring="   "),
    "a case with no steps": lambda s: s["pytest_cases"][0].update(steps=[]),
    "a step with no code": lambda s: s["pytest_cases"][0]["steps"][0].update(code=""),
}


@needs_node
def test_both_validators_accept_a_good_suite(sample):
    assert python_accepts(sample)
    assert js_accepts(sample)


@needs_node
@pytest.mark.parametrize("what", list(MALFORMED), ids=list(MALFORMED))
def test_both_validators_reject_the_same_suites(sample, what):
    suite = broken(sample, MALFORMED[what])
    assert not python_accepts(suite), f"Python accepted a suite with {what}"
    assert not js_accepts(suite), f"site/app.js accepted a suite with {what}"
