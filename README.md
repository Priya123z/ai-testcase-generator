# AI Test-Case Generator

[![Tests](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)
![Model](https://img.shields.io/badge/model-gpt--4o--mini-green.svg)

A Python tool that converts plain-text user stories into structured **Gherkin BDD scenarios** and **Pytest test skeletons** using AI via [OpenRouter](https://openrouter.ai). Pydantic models enforce structured output — if the model returns invalid JSON the generator raises a `ValueError` instead of silently producing broken tests. Ships with a Streamlit web UI for QA team self-service.

---

## How it works

```
User Story (plain text)
        ↓
   OpenRouter AI (gpt-4o-mini)
        ↓  returns structured JSON
   Pydantic TestSuite validation
        ↓
   Three export formats:
   • Gherkin .feature file
   • Pytest .py skeleton
   • Raw JSON
```

1. Paste a user story with acceptance criteria
2. The AI generates 3–7 Gherkin scenarios (happy path + negative paths + edge cases) and matching Pytest function skeletons
3. A Pydantic model (`TestSuite`) validates every field — hallucinated structures are rejected before they reach you
4. Download the `.feature` or `.py` file, or copy the JSON

---

## Example output

Given the login story in `examples/login_story.txt`:

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
    Then an inline error "Email is required" is displayed
```

---

## Quick start

```bash
git clone https://github.com/Priya123z/ai-testcase-generator.git
cd ai-testcase-generator

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
streamlit run app/streamlit_app.py
```

Open http://localhost:8501, paste a user story, click **Generate**.

---

## Get an OpenRouter API key

1. Sign up free at [openrouter.ai](https://openrouter.ai)
2. Go to **Keys** → **Create Key**
3. Copy the key (starts with `sk-or-v1-...`)
4. Paste it into your `.env` file:
   ```
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```

The default model is **`openai/gpt-4o-mini`** — extremely cheap (~$0.00015 per 1K input tokens) and excellent at structured JSON output. You can override it programmatically:

```python
suite = generate_test_suite(story, model="anthropic/claude-3-haiku")
```

Other well-priced options on OpenRouter: `google/gemini-flash-1.5`, `anthropic/claude-3-haiku`, `mistralai/mistral-7b-instruct`.

---

## Run tests (no API key needed)

All tests mock the OpenRouter client — the full suite runs in CI without a live API call.

```bash
pytest tests/ -v
```

---

## Add API key to GitHub Actions

For live integration tests in CI, add your key as a repository secret:

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `OPENROUTER_API_KEY`, Value: your key
4. Reference it in your workflow: `env: OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}`

The existing CI workflow (`tests.yml`) runs only mocked tests and does **not** require this secret.

---

## Prompt versioning

`app/prompts.py` contains versioned system prompts (`SYSTEM_PROMPT_V1`). Changing the prompt strategy is a one-file change — the rest of the codebase is decoupled from prompt content, so iterating on prompt quality does not scatter changes across modules.

---

## Honest caveats

Generated tests are starting points for QA review, not a replacement for human test design. The generator excels at happy-path and obvious negative-path scenarios but misses domain-specific edge cases that require business context. Every response includes a `coverage_notes` field that explicitly calls out what it chose not to generate.

---

## Project structure

```
ai-testcase-generator/
├── app/
│   ├── generator.py        # Core: OpenRouter call, JSON parse, fence-stripping, serialisers
│   ├── models.py           # Pydantic models (TestSuite, GherkinScenario, …)
│   ├── prompts.py          # Versioned system prompts (SYSTEM_PROMPT_V1)
│   └── streamlit_app.py    # Streamlit web UI
├── tests/
│   └── test_generator.py   # 11 unit tests — all mocked, no API key needed
├── examples/
│   ├── login_story.txt
│   └── checkout_story.txt
├── .github/workflows/
│   └── tests.yml           # CI: pytest on push/PR (mocked, no key needed)
├── .env.example            # Copy to .env and add your OPENROUTER_API_KEY
├── requirements.txt
└── README.md
```

---

Built by Priya Bhagoriya | [LinkedIn](https://linkedin.com/in/priya-bhagoriya)
