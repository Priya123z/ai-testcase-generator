# AI Test-Case Generator

[![Tests](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)

A Python tool that converts plain-text user stories into structured Gherkin scenarios and Pytest test skeletons using the Anthropic Claude API. Pydantic models enforce structured output so the generator never returns unvalidated free text. Ships with a Streamlit UI for QA team self-service.

![Demo screenshot](docs/demo.png)

> A GIF of the Streamlit UI in action will be added here.

---

## How it works

1. You paste a user story (plain text, acceptance criteria welcome)
2. Claude analyses it and returns a structured JSON object — feature name, Gherkin scenarios with typed steps, Pytest function skeletons, and coverage notes
3. A Pydantic model (`TestSuite`) validates every field — if the LLM hallucinates an invalid structure, the generator raises a `ValueError` rather than silently producing broken output
4. The Streamlit UI renders three tabs: Gherkin `.feature` file, Python `.py` file, raw JSON — each downloadable

---

## Example output

Given the login user story in `examples/login_story.txt`, the generator produces:

```gherkin
Feature: User Login

  @smoke
  Scenario: Successful login with valid credentials
    Given a registered user with email "user@test.com"
    When they submit the login form with password "SecurePass123"
    Then they are redirected to /dashboard

  @security
  Scenario: Account lockout after 3 failed login attempts
    Given a registered user with email "user@test.com"
    When they enter an incorrect password 3 times consecutively
    Then the account is locked
    And a lockout notification email is sent to "user@test.com"

  @validation
  Scenario: Empty email field shows inline validation error
    Given the login page is open
    When the user submits the form with an empty email field
    Then an inline error "Email is required" is displayed beneath the email field
```

---

## Quick start

```bash
git clone https://github.com/Priya123z/ai-testcase-generator.git
cd ai-testcase-generator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
streamlit run app/streamlit_app.py
```

---

## Run tests (no API key needed)

All tests mock the Anthropic client, so the full suite runs in CI without a live API key.

```bash
pytest tests/ -v
```

---

## Prompt versioning

`app/prompts.py` contains versioned system prompts (`SYSTEM_PROMPT_V1`, `SYSTEM_PROMPT_VERSION`). Changing the prompt strategy — adding new output fields, adjusting tone, tightening JSON rules — is a one-file change. The rest of the codebase is decoupled from prompt content, so iterating on prompt quality does not scatter changes across modules.

---

## Honest caveats

Generated tests are starting points for QA review, not a replacement for human test design. The generator excels at happy-path and obvious negative-path scenarios but will miss domain-specific edge cases that require business context. The `coverage_notes` field in every response explicitly calls out what it chose not to generate.

---

## Project structure

```
ai-testcase-generator/
├── app/
│   ├── __init__.py
│   ├── generator.py        # Core logic: API call, JSON parse, serialisers
│   ├── models.py           # Pydantic models (TestSuite, GherkinScenario, …)
│   ├── prompts.py          # Versioned system prompts
│   └── streamlit_app.py    # Streamlit UI
├── tests/
│   ├── __init__.py
│   └── test_generator.py   # Unit tests with mocked LLM
├── examples/
│   ├── login_story.txt
│   └── checkout_story.txt
├── .github/
│   └── workflows/
│       └── tests.yml       # CI: run pytest on push/PR
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

Built by Priya Bhagoriya | [LinkedIn](https://linkedin.com/in/priya-bhagoriya)
