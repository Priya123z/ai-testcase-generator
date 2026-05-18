import json
import os
import re
from openai import OpenAI
from .models import TestSuite
from .prompts import SYSTEM_PROMPT_V1

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY") or "sk-or-placeholder",
    base_url="https://openrouter.ai/api/v1",
)

DEFAULT_MODEL = "openai/gpt-4o-mini"


def _strip_fences(text: str) -> str:
    """Strip markdown code fences that some models wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def generate_test_suite(user_story: str, model: str = DEFAULT_MODEL) -> TestSuite:
    """Convert a plain-text user story into a structured TestSuite via OpenRouter.

    Raises:
        ValueError: if the LLM returns malformed JSON or Pydantic validation fails
        openai.APIError: on network or auth issues
    """
    message = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_V1},
            {
                "role": "user",
                "content": f"Generate test cases for this user story:\n\n{user_story}",
            },
        ],
    )
    raw = _strip_fences(message.choices[0].message.content)
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
