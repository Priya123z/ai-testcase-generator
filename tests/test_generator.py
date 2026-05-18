import json
import pytest
from unittest.mock import patch, MagicMock
from app.generator import generate_test_suite, suite_to_gherkin, suite_to_pytest
from app.models import TestSuite, GherkinScenario, GherkinStep, PytestTestCase, PytestStep


MOCK_RESPONSE_JSON = {
    "feature": "User Login",
    "scenarios": [
        {
            "name": "Successful login with valid credentials",
            "tags": ["smoke"],
            "steps": [
                {"keyword": "Given", "text": 'a registered user with email "user@test.com"'},
                {"keyword": "When", "text": 'they submit the login form with password "SecurePass123"'},
                {"keyword": "Then", "text": "they are redirected to /dashboard"},
            ]
        },
        {
            "name": "Account lockout after 3 failed attempts",
            "tags": ["security"],
            "steps": [
                {"keyword": "Given", "text": 'a registered user with email "user@test.com"'},
                {"keyword": "When", "text": "they enter wrong credentials 3 times"},
                {"keyword": "Then", "text": "the account is locked"},
                {"keyword": "And", "text": "further login attempts are rejected"},
            ]
        }
    ],
    "pytest_cases": [
        {
            "function_name": "test_valid_login_redirects_to_dashboard",
            "docstring": "Valid credentials should redirect to /dashboard",
            "steps": [
                {"description": "Login with valid credentials", "code": "response = client.post('/login', json={'email': 'user@test.com', 'password': 'SecurePass123'})"},
                {"description": "Assert redirect", "code": "assert response.status_code == 302"},
            ]
        }
    ],
    "coverage_notes": "MFA flows and OAuth are out of scope for this story."
}


@pytest.fixture
def mock_anthropic_response():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps(MOCK_RESPONSE_JSON))]
    return mock_msg


class TestGenerateTestSuite:
    def test_returns_test_suite_instance(self, mock_anthropic_response):
        with patch("app.generator.client") as mock_client:
            mock_client.messages.create.return_value = mock_anthropic_response
            result = generate_test_suite("As a user, I want to log in")
        assert isinstance(result, TestSuite)

    def test_feature_name_populated(self, mock_anthropic_response):
        with patch("app.generator.client") as mock_client:
            mock_client.messages.create.return_value = mock_anthropic_response
            result = generate_test_suite("As a user, I want to log in")
        assert result.feature == "User Login"

    def test_scenarios_count_matches(self, mock_anthropic_response):
        with patch("app.generator.client") as mock_client:
            mock_client.messages.create.return_value = mock_anthropic_response
            result = generate_test_suite("As a user, I want to log in")
        assert len(result.scenarios) == 2

    def test_coverage_notes_populated(self, mock_anthropic_response):
        with patch("app.generator.client") as mock_client:
            mock_client.messages.create.return_value = mock_anthropic_response
            result = generate_test_suite("As a user, I want to log in")
        assert len(result.coverage_notes) > 0

    def test_invalid_json_raises_value_error(self):
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text="this is not json")]
        with patch("app.generator.client") as mock_client:
            mock_client.messages.create.return_value = bad_msg
            with pytest.raises(ValueError, match="invalid JSON"):
                generate_test_suite("test story")


class TestSuiteToGherkin:
    def test_gherkin_contains_feature_name(self):
        suite = TestSuite.model_validate(MOCK_RESPONSE_JSON)
        gherkin = suite_to_gherkin(suite)
        assert "Feature: User Login" in gherkin

    def test_gherkin_contains_scenario_name(self):
        suite = TestSuite.model_validate(MOCK_RESPONSE_JSON)
        gherkin = suite_to_gherkin(suite)
        assert "Scenario: Successful login with valid credentials" in gherkin

    def test_gherkin_contains_steps(self):
        suite = TestSuite.model_validate(MOCK_RESPONSE_JSON)
        gherkin = suite_to_gherkin(suite)
        assert "Given" in gherkin
        assert "When" in gherkin
        assert "Then" in gherkin


class TestSuiteToPytest:
    def test_pytest_contains_imports(self):
        suite = TestSuite.model_validate(MOCK_RESPONSE_JSON)
        pytest_code = suite_to_pytest(suite)
        assert "import pytest" in pytest_code

    def test_pytest_contains_function_name(self):
        suite = TestSuite.model_validate(MOCK_RESPONSE_JSON)
        pytest_code = suite_to_pytest(suite)
        assert "def test_valid_login_redirects_to_dashboard" in pytest_code
