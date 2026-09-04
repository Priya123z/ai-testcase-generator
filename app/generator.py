import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from .models import TestSuite
from .prompts import SYSTEM_PROMPT_V1

load_dotenv()

ATTEMPTS_PER_PROVIDER = 3

# Groq first. Its free tier allows 1000 requests a day against OpenRouter's 50, and
# it supports a real JSON mode so the response does not have to be scraped out of
# prose. Both speak the OpenAI wire format, so one client class covers them.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        # A free slug: the paid ones stop working once an account hits zero balance.
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
}


def available_providers(api_key: str = None):
    """A supplied key is treated as a Groq key, which is what the UI passes through."""
    if api_key:
        return [("groq", api_key)]
    return [(name, os.environ.get(cfg["env"])) for name, cfg in PROVIDERS.items()
            if os.environ.get(cfg["env"])]


def _client(provider: str, api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=PROVIDERS[provider]["base_url"])


def _strip_fences(text: str) -> str:
    """Strip markdown code fences that some models wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def generate_test_suite(user_story: str, model: str = None, api_key: str = None) -> TestSuite:
    """Convert a user story into a structured TestSuite.

    Tries each configured provider in turn, because the free tiers rate limit
    without warning and one provider is not enough to stay usable.
    """
    providers = available_providers(api_key)
    if not providers:
        raise RuntimeError(
            "No API key found. Set GROQ_API_KEY (or OPENROUTER_API_KEY) in .env, "
            "or paste a key into the app."
        )

    errors = []
    for provider, key in providers:
        # The requested shape nests generated code inside JSON strings, so a model
        # occasionally emits a stray brace and strict JSON mode rejects the whole
        # response. Sampling again usually produces valid output; this is a property
        # of the model, not of the prompt.
        for attempt in range(ATTEMPTS_PER_PROVIDER):
            try:
                return _generate_with(provider, key, user_story, model)
            except Exception as exc:
                errors.append(f"{provider} attempt {attempt + 1}: {_short(exc)}")

    raise RuntimeError("Every provider failed  " + "; ".join(errors))


def _short(exc: Exception, limit: int = 160) -> str:
    text = str(exc).replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def _generate_with(provider: str, key: str, user_story: str, model: str = None) -> TestSuite:
    response = _client(provider, key).chat.completions.create(
        model=model or PROVIDERS[provider]["model"],
        max_tokens=8000,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_V1},
            {
                "role": "user",
                "content": f"Generate test cases for this user story:\n\n{user_story}",
            },
        ],
    )

    raw = _strip_fences(response.choices[0].message.content or "")
    if not raw:
        raise ValueError("model returned nothing")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e

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
