"""
Integration tests for the AI test-case generator.

All positive-path tests call the real OpenRouter API (gpt-4o-mini).
A module-scoped fixture makes exactly ONE API call and shares the result
across every positive test — minimising cost and latency.

The two error-handling tests at the bottom still patch the network layer
because you cannot reliably force a remote LLM to return broken JSON on
demand; those tests verify the generator's defensive parsing logic, not
the LLM's behaviour.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

from app.generator import generate_test_suite, suite_to_gherkin, suite_to_pytest
from app.models import TestSuite

load_dotenv()

LOGIN_STORY = """As a registered user, I want to log in with my email and password
so that I can access my dashboard.

Acceptance criteria:
- Valid credentials redirect to /dashboard
- Invalid password shows "Credentials do not match" error message
- Empty email field shows inline "Email is required" validation error
- Empty password field shows inline "Password is required" validation error
- Account locks after 3 consecutive failed login attempts
"""


@pytest.fixture(scope="module")
def real_suite() -> TestSuite:
    """Call OpenRouter once for the entire module. Cost: 1 API call."""
    return generate_test_suite(LOGIN_STORY)


# ---------------------------------------------------------------------------
# Real API: structure validation
# ---------------------------------------------------------------------------

class TestAPIOutput:
    def test_returns_test_suite_instance(self, real_suite):
        assert isinstance(real_suite, TestSuite)

    def test_feature_name_is_non_empty(self, real_suite):
        assert len(real_suite.feature.strip()) > 0

    def test_generates_between_3_and_7_scenarios(self, real_suite):
        count = len(real_suite.scenarios)
        assert 3 <= count <= 7, f"Expected 3–7 scenarios, got {count}"

    def test_every_scenario_has_a_name(self, real_suite):
        for s in real_suite.scenarios:
            assert len(s.name.strip()) > 0

    def test_every_scenario_has_at_least_one_step(self, real_suite):
        for s in real_suite.scenarios:
            assert len(s.steps) >= 1, f"Scenario '{s.name}' has no steps"

    def test_step_keywords_are_valid_gherkin(self, real_suite):
        valid = {"Given", "When", "Then", "And", "But"}
        for s in real_suite.scenarios:
            for step in s.steps:
                assert step.keyword in valid, f"Bad keyword '{step.keyword}' in '{s.name}'"

    def test_has_at_least_one_pytest_case(self, real_suite):
        assert len(real_suite.pytest_cases) >= 1

    def test_all_pytest_function_names_start_with_test_(self, real_suite):
        for tc in real_suite.pytest_cases:
            assert tc.function_name.startswith("test_"), \
                f"Function name must start with test_: got '{tc.function_name}'"

    def test_all_pytest_function_names_are_snake_case(self, real_suite):
        for tc in real_suite.pytest_cases:
            name = tc.function_name
            assert name == name.lower() and " " not in name, \
                f"Not snake_case: '{name}'"

    def test_each_pytest_case_has_a_docstring(self, real_suite):
        for tc in real_suite.pytest_cases:
            assert len(tc.docstring.strip()) > 0

    def test_coverage_notes_are_present(self, real_suite):
        assert len(real_suite.coverage_notes.strip()) > 10


# ---------------------------------------------------------------------------
# Real API: Gherkin serialiser
# ---------------------------------------------------------------------------

class TestGherkinOutput:
    def test_starts_with_feature_keyword(self, real_suite):
        gherkin = suite_to_gherkin(real_suite)
        assert gherkin.startswith("Feature:")

    def test_contains_scenario_keyword(self, real_suite):
        gherkin = suite_to_gherkin(real_suite)
        assert "Scenario:" in gherkin

    def test_contains_given_when_then(self, real_suite):
        gherkin = suite_to_gherkin(real_suite)
        assert "Given" in gherkin
        assert "When" in gherkin
        assert "Then" in gherkin

    def test_feature_name_appears_in_output(self, real_suite):
        gherkin = suite_to_gherkin(real_suite)
        assert real_suite.feature in gherkin

    def test_all_scenario_names_appear_in_output(self, real_suite):
        gherkin = suite_to_gherkin(real_suite)
        for scenario in real_suite.scenarios:
            assert scenario.name in gherkin, \
                f"Scenario '{scenario.name}' missing from Gherkin output"


# ---------------------------------------------------------------------------
# Real API: Pytest serialiser
# ---------------------------------------------------------------------------

class TestPytestOutput:
    def test_output_starts_with_import_pytest(self, real_suite):
        code = suite_to_pytest(real_suite)
        assert "import pytest" in code

    def test_output_contains_function_definitions(self, real_suite):
        code = suite_to_pytest(real_suite)
        assert "def test_" in code

    def test_all_function_names_present_in_output(self, real_suite):
        code = suite_to_pytest(real_suite)
        for tc in real_suite.pytest_cases:
            assert tc.function_name in code

    def test_output_contains_docstrings(self, real_suite):
        code = suite_to_pytest(real_suite)
        assert '"""' in code


# ---------------------------------------------------------------------------
# Error-path tests — these MUST patch the network layer because you cannot
# reliably instruct a live LLM to return intentionally broken JSON.
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_invalid_json_raises_value_error(self):
        """Generator must raise ValueError when the LLM returns non-JSON."""
        bad = MagicMock()
        bad.choices = [MagicMock(message=MagicMock(content="not json at all {{"))]
        with patch("app.generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = bad
            with pytest.raises(ValueError, match="invalid JSON"):
                generate_test_suite("test story")

    def test_markdown_fenced_json_is_parsed(self):
        """Models sometimes wrap JSON in ```json...``` — the generator must strip it."""
        valid_data = {
            "feature": "Login",
            "scenarios": [{"name": "Valid login redirects to dashboard", "tags": [], "steps": [
                {"keyword": "Given", "text": "user is on the login page"},
                {"keyword": "When", "text": "they submit valid credentials"},
                {"keyword": "Then", "text": "they are redirected to /dashboard"},
            ]}],
            "pytest_cases": [{"function_name": "test_valid_login", "docstring": "Valid login",
                               "steps": [{"description": "login", "code": "pass"}]}],
            "coverage_notes": "MFA and OAuth are out of scope",
        }
        fenced = f"```json\n{json.dumps(valid_data)}\n```"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=fenced))]
        with patch("app.generator.client") as mock_client:
            mock_client.chat.completions.create.return_value = mock_resp
            result = generate_test_suite("test story")
        assert isinstance(result, TestSuite)
        assert result.feature == "Login"
