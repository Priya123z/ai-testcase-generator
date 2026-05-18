import json
import os
from anthropic import Anthropic
from .models import TestSuite
from .prompts import SYSTEM_PROMPT_V1


client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def generate_test_suite(user_story: str, model: str = "claude-3-5-sonnet-20241022") -> TestSuite:
    """Convert a plain-text user story into a structured TestSuite.

    Raises:
        ValueError: if the LLM returns malformed JSON or Pydantic validation fails
        anthropic.APIError: on network or auth issues
    """
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT_V1,
        messages=[
            {
                "role": "user",
                "content": f"Generate test cases for this user story:\n\n{user_story}"
            }
        ]
    )
    raw = message.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw output:\n{raw}") from e
    return TestSuite.model_validate(data)


def suite_to_gherkin(suite: TestSuite) -> str:
    lines = [f"Feature: {suite.feature}", ""]
    for scenario in suite.scenarios:
        if scenario.tags:
            lines.append("  " + " ".join(f"@{t}" for t in scenario.tags))
        lines.append(f"  Scenario: {scenario.name}")
        for step in scenario.steps:
            lines.append(f"    {step.keyword} {step.text}")
        lines.append("")
    return "\n".join(lines)


def suite_to_pytest(suite: TestSuite) -> str:
    lines = ["import pytest", "", ""]
    for tc in suite.pytest_cases:
        lines.append(f"def {tc.function_name}():")
        lines.append(f'    """{tc.docstring}"""')
        for step in tc.steps:
            lines.append(f"    # {step.description}")
            lines.append(f"    {step.code}")
        lines.append("")
    return "\n".join(lines)
