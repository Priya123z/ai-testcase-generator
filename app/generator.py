import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from .prompts import SYSTEM_PROMPT_V1

load_dotenv()

ATTEMPTS_PER_MODEL = 2

# Groq first. Its free tier allows 1000 requests a day against OpenRouter's 50, and
# it supports a real JSON mode so the response does not have to be scraped out of
# prose. Both speak the OpenAI wire format, so one client class covers them.
#
# Each provider lists smaller models to fall back to. What actually runs out on
# the free tier is tokens per minute, not requests per day, and asking the same
# model again inside the same minute cannot succeed: three attempts at the
# 120b model is three guaranteed 429s. A smaller model has its own allowance.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
        "fallbacks": ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        # A free slug: the paid ones stop working once an account hits zero balance.
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "fallbacks": [],
    },
}


def _is_rate_limit(exc):
    return "429" in str(exc) or "rate limit" in str(exc).lower()


def available_providers(api_key=None):
    """A key passed in is treated as a Groq key, and used on its own.

    That is the bring-your-own-key path: a caller with their own key should not
    silently fall through to mine.
    """
    if api_key:
        return [("groq", api_key)]
    return [(name, os.environ.get(cfg["env"])) for name, cfg in PROVIDERS.items()
            if os.environ.get(cfg["env"])]


def _client(provider, api_key):
    return OpenAI(api_key=api_key, base_url=PROVIDERS[provider]["base_url"])


def _strip_fences(text):
    """Strip markdown code fences that some models wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


GHERKIN_KEYWORDS = ("Given", "When", "Then", "And", "But")


def check_suite(data):
    """Reject almost-right model output at the boundary.

    A suite that is missing a field, or carries a step keyword that is not
    Gherkin, or a test name pytest will never collect, produces files that fail
    confusingly much later. The browser demo runs the same checks in JavaScript
    (site/app.js), so both paths accept exactly the same answers.
    """
    if not isinstance(data, dict):
        raise ValueError("the model did not return an object")
    if not str(data.get("feature", "")).strip():
        raise ValueError("no feature name")
    if not str(data.get("coverage_notes", "")).strip():
        raise ValueError("no coverage_notes")

    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("no scenarios")
    for sc in scenarios:
        if not str(sc.get("name", "")).strip():
            raise ValueError("a scenario has no name")
        steps = sc.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"scenario {sc['name']!r} has no steps")
        for st in steps:
            if st.get("keyword") not in GHERKIN_KEYWORDS:
                raise ValueError(f"{st.get('keyword')!r} is not a Gherkin keyword")
            if not str(st.get("text", "")).strip():
                raise ValueError(f"a step in {sc['name']!r} has no text")
        sc.setdefault("tags", [])

    cases = data.get("pytest_cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("no pytest_cases")
    for tc in cases:
        name = tc.get("function_name", "")
        if not re.fullmatch(r"test_[a-z0-9_]*", name or ""):
            raise ValueError(f"{name!r} is not a snake_case test name")
        # Both serialisers write the docstring straight into the generated file,
        # so a missing one is a KeyError here and the string "undefined" in the
        # browser. Neither validator used to look for it.
        if not str(tc.get("docstring", "")).strip():
            raise ValueError(f"{name} has no docstring")
        if not isinstance(tc.get("steps"), list) or not tc["steps"]:
            raise ValueError(f"{name} has no steps")
        for st in tc["steps"]:
            if not str(st.get("code", "")).strip():
                raise ValueError(f"a step in {name} has no code")

    return data


def generate_test_suite(user_story, model=None, api_key=None):
    """Convert a user story into a checked suite dict.

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
        # An explicit model gets tried on its own; otherwise walk the provider's
        # preferred model and then its smaller ones.
        candidates = [model] if model else [PROVIDERS[provider]["model"]] + PROVIDERS[provider]["fallbacks"]

        for candidate in candidates:
            # The requested shape nests generated code inside JSON strings, so a
            # model occasionally emits a stray brace and strict JSON mode rejects
            # the whole response. Sampling again usually fixes that; it is a
            # property of the model, not of the prompt.
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    return _generate_with(provider, key, user_story, candidate)
                except Exception as exc:
                    errors.append(f"{provider}/{candidate} attempt {attempt + 1}: {_short(exc)}")
                    if _is_rate_limit(exc):
                        break  # this model is out of allowance; a retry cannot help

    raise RuntimeError("Every provider failed. " + "; ".join(errors))


def _short(exc, limit=160):
    text = str(exc).replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def _generate_with(provider, key, user_story, model=None):
    response = _client(provider, key).chat.completions.create(
        model=model or PROVIDERS[provider]["model"],
        # Matches site/app.js, so the same story gives the same kind of answer
        # whichever path a caller takes.
        temperature=0.2,
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

    return check_suite(data)


def suite_to_gherkin(suite):
    lines = [f"Feature: {suite['feature']}", ""]
    for scenario in suite["scenarios"]:
        if scenario.get("tags"):
            lines.append("  " + " ".join(f"@{t}" for t in scenario["tags"]))
        lines.append(f"  Scenario: {scenario['name']}")
        for step in scenario["steps"]:
            lines.append(f"    {step['keyword']} {step['text']}")
        lines.append("")
    return "\n".join(lines)


def suite_to_pytest(suite):
    lines = ["import pytest", "", ""]
    for tc in suite["pytest_cases"]:
        lines.append(f"def {tc['function_name']}():")
        lines.append(f'    """{tc["docstring"]}"""')
        for step in tc["steps"]:
            lines.append(f"    # {step['description']}")
            lines.append(f"    {step['code']}")
        lines.append("")
    return "\n".join(lines)
