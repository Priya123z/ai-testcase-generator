# DEEP DIVE: ai-testcase-generator

> A portfolio deep-dive document covering architecture, design decisions, and interview preparation.

---

## Table of Contents

1. [What It Is — Three Levels](#1-what-it-is--three-levels)
2. [Architecture Diagram](#2-architecture-diagram)
3. [How to Run](#3-how-to-run)
4. [How to Validate It Works](#4-how-to-validate-it-works)
5. [Interview Q&A (25 Questions)](#5-interview-qa-25-questions)

---

## 1. What It Is — Three Levels

### Level 1 — Simple (Non-Technical)

You write a sentence describing what a feature of an app should do — for example, *"As a user, I want to log in with my email and password."* The tool sends that sentence to an AI, and within seconds the AI writes a full set of test cases for you: tests that check what happens when login works, what happens when the password is wrong, what happens when the account is locked, and so on. Those tests are saved as ready-to-use files that a developer can plug straight into their testing framework. Instead of a developer spending an hour manually writing test cases, this tool does it in about five seconds.

### Level 2 — Intermediate (How the Pipeline Works)

The project is a Python web application with a clear separation between the AI layer, the data validation layer, and the user interface.

**File-by-file breakdown:**

| File | Role |
|---|---|
| `app/generator.py` | Core business logic — calls the LLM, parses the response, serialises output |
| `app/models.py` | Pydantic data models — defines and enforces the exact shape of LLM output |
| `app/prompts.py` | System prompt template — instructs the LLM on format and content rules |
| `app/streamlit_app.py` | Web UI — text area, Generate button, tabbed output, download buttons |
| `tests/test_generator.py` | 22 tests — 20 integration tests against real API, 2 mock-based error-path tests |

**The pipeline in plain English:**

1. The user pastes a user story into the Streamlit web UI.
2. Streamlit calls `generate_test_suite()` in `generator.py`.
3. `generator.py` loads the OpenRouter API key from `.env`, constructs an `openai.OpenAI` client pointed at `https://openrouter.ai/api/v1`, and fires a chat completion request using model `openai/gpt-4o-mini`.
4. The LLM receives `SYSTEM_PROMPT_V1` (which demands valid JSON, no markdown fences, 3-7 scenarios, snake_case function names) plus the user story as the human message.
5. The raw text response passes through `_strip_fences()`, which defensively removes any ``` backtick fences the model may have added despite instructions.
6. The cleaned string is parsed with `json.loads()`, then passed into the `TestSuite` Pydantic model. Pydantic validates every field recursively — if any field is missing, has the wrong type, or violates a constraint, a `ValidationError` is raised immediately.
7. On success, `suite_to_gherkin()` and `suite_to_pytest()` serialise the validated `TestSuite` object into `.feature` text and `.py` skeleton text respectively.
8. The Streamlit UI renders three tabs: Gherkin, Pytest, and raw JSON — each with a download button.

### Level 3 — Advanced (Design Decisions)

**Why Pydantic over raw dict access?**

Raw `dict` access like `data["scenarios"][0]["steps"]` fails silently in surprising ways — a missing key raises a `KeyError` at an arbitrary point in the serialiser, a wrong type causes a confusing `AttributeError` downstream, and there is no single place to read what the expected shape is. Pydantic solves all three problems simultaneously: it acts as a typed contract, validates at the boundary, and provides a human-readable schema. When the LLM hallucinates a field name (`"test_steps"` instead of `"steps"`), Pydantic catches it at parse time and raises a `ValidationError` with a precise message — the error never reaches the serialisers. The Pydantic models also serve as living documentation of the LLM output contract.

**Why prompt versioning in `prompts.py`?**

Prompt engineering is iterative. If the system prompt were embedded directly in `generator.py`, every prompt tweak would be a change to business logic, making diffs noisy and blame tracking hard. By isolating prompts in `prompts.py` with explicit version names (`SYSTEM_PROMPT_V1`), the team can add `SYSTEM_PROMPT_V2` for experimentation, run both in an A/B test, and compare output quality — without touching any other file. It also makes it trivial to roll back a prompt change independently of a code change.

**Why a module-scoped fixture for 22 tests?**

Each call to the OpenRouter API costs money and adds latency. If every test function triggered its own API call, a 22-test suite would make 22 real HTTP requests — slow (each takes 2-5 seconds) and expensive. With `scope="module"`, pytest calls the fixture once per test module, stores the returned `TestSuite` object, and injects it into all 20 tests that need it. The entire suite makes exactly 1 API call. The 2 error-path tests use `unittest.mock.patch` to simulate bad responses without any network activity.

**LLM reliability challenges and mitigations:**

LLMs are non-deterministic and instruction-following is imperfect. This project addresses reliability at three layers:

- *Instruction layer:* `SYSTEM_PROMPT_V1` specifies exact constraints (JSON only, no fences, 3-7 scenarios, snake_case, `test_` prefix). Being explicit reduces, but does not eliminate, non-compliance.
- *Parsing layer:* `_strip_fences()` handles the most common form of non-compliance — wrapping output in ```json fences.
- *Validation layer:* Pydantic rejects structurally invalid responses before they corrupt downstream output.

What this does not handle: semantically wrong test cases (the LLM writes syntactically valid tests for the wrong feature), hallucinated scenario names that don't match the user story, or subtly broken Pytest code. These are harder to catch automatically and represent the main limitation of AI-generated tests — they require human review before merging.

---

## 2. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        USER (Browser)                            │
│                                                                  │
│   Pastes user story into Streamlit text area                     │
│   Clicks "Generate Test Suite"                                   │
└────────────────────────┬─────────────────────────────────────────┘
                         │  user_story: str
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   streamlit_app.py (UI Layer)                    │
│                                                                  │
│   - Loads .env (OPENROUTER_API_KEY)                              │
│   - Calls generate_test_suite(user_story)                        │
│   - Renders 3 tabs + download buttons                            │
└────────────────────────┬─────────────────────────────────────────┘
                         │  user_story: str
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   generator.py (Core Logic)                      │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  OpenAI client → openrouter.ai/api/v1                   │     │
│  │  model: openai/gpt-4o-mini                              │     │
│  │  messages: [SYSTEM_PROMPT_V1, user_story]               │     │
│  └───────────────────────┬─────────────────────────────────┘     │
│                          │  raw LLM text                         │
│  ┌───────────────────────▼─────────────────────────────────┐     │
│  │  _strip_fences()                                        │     │
│  │  Removes ```json ... ``` wrappers if present            │     │
│  └───────────────────────┬─────────────────────────────────┘     │
│                          │  clean JSON string                    │
│  ┌───────────────────────▼─────────────────────────────────┐     │
│  │  json.loads()  →  raw dict                              │     │
│  └───────────────────────┬─────────────────────────────────┘     │
│                          │  dict                                 │
└────────────────────────┬─────────────────────────────────────────┘
                         │  dict
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   models.py (Validation Layer)                   │
│                                                                  │
│   TestSuite.model_validate(dict)                                 │
│                                                                  │
│   TestSuite                                                      │
│   ├── feature: str                                               │
│   ├── scenarios: list[GherkinScenario]                           │
│   │   └── GherkinScenario                                        │
│   │       ├── name: str                                          │
│   │       ├── tags: list[str]                                    │
│   │       └── steps: list[GherkinStep]                           │
│   │           └── GherkinStep                                    │
│   │               ├── keyword: str  (Given/When/Then/And)        │
│   │               └── text: str                                  │
│   ├── pytest_cases: list[PytestTestCase]                         │
│   │   └── PytestTestCase                                         │
│   │       ├── function_name: str  (must start with test_)        │
│   │       ├── docstring: str                                      │
│   │       └── steps: list[PytestStep]                            │
│   │           └── PytestStep                                     │
│   │               ├── description: str                           │
│   │               └── code: str                                  │
│   └── coverage_notes: list[str]                                  │
│                                                                  │
│   ValidationError raised here if LLM output is malformed        │
└────────────────────────┬─────────────────────────────────────────┘
                         │  TestSuite (validated object)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│              Serialisers in generator.py                         │
│                                                                  │
│   suite_to_gherkin(suite)   →   .feature file text              │
│   suite_to_pytest(suite)    →   .py skeleton text               │
│   suite.model_dump_json()   →   raw JSON string                  │
└────────────────────────┬─────────────────────────────────────────┘
                         │  3 string outputs
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Streamlit UI (3 Tabs)                          │
│                                                                  │
│   Tab 1: Gherkin (.feature)   [Download button]                  │
│   Tab 2: Pytest (.py)         [Download button]                  │
│   Tab 3: Raw JSON             [Download button]                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. How to Run

### Prerequisites

- Python 3.10 or higher
- An OpenRouter account with an API key — sign up free at [openrouter.ai](https://openrouter.ai)

### Step-by-Step

```bash
# 1. Clone the repository
git clone https://github.com/priya123z/ai-testcase-generator.git
cd ai-testcase-generator

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# Open .env in any editor and set:
# OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 5. Launch the Streamlit web UI
streamlit run app/streamlit_app.py
# Opens automatically at http://localhost:8501

# 6. Run the test suite (requires a valid OPENROUTER_API_KEY in .env)
pytest tests/ -v
```

### What Each Dependency Does

| Package | Version | Purpose |
|---|---|---|
| `openai` | >=1.30.0 | HTTP client for OpenRouter (uses OpenAI-compatible API) |
| `streamlit` | 1.35.0 | Web UI framework — no HTML/CSS needed |
| `pydantic` | 2.7.4 | Data validation and schema enforcement for LLM output |
| `python-dotenv` | 1.0.1 | Loads `OPENROUTER_API_KEY` from `.env` file |
| `pytest` | 8.2.2 | Test runner |

---

## 4. How to Validate It Works

### After Running the UI

1. Navigate to `http://localhost:8501`.
2. You should see a text area labelled with something like *"Enter your user story"*.
3. Paste this story: `As a registered user, I want to log in with my email and password so that I can access my account.`
4. Click **Generate Test Suite**.
5. After 3-8 seconds, three tabs appear:
   - **Gherkin tab** — Contains a `.feature` file with `Feature:`, `Scenario:`, `Given`, `When`, `Then` keywords. You should see 3-7 scenarios covering happy path, wrong password, empty fields, etc.
   - **Pytest tab** — Contains Python functions named `test_<something>`, each with a docstring and commented step descriptions.
   - **JSON tab** — Contains raw JSON with keys `feature`, `scenarios`, `pytest_cases`, and `coverage_notes`.
6. Each tab has a **Download** button. Click it and verify the file downloads with the correct extension (`.feature`, `.py`, `.json`).

### After Running Tests

```
pytest tests/ -v
```

**Expected terminal output (abbreviated):**

```
tests/test_generator.py::test_suite_has_feature_name PASSED
tests/test_generator.py::test_scenarios_count_in_range PASSED
tests/test_generator.py::test_all_scenarios_have_names PASSED
tests/test_generator.py::test_all_steps_have_valid_keywords PASSED
tests/test_generator.py::test_pytest_cases_exist PASSED
tests/test_generator.py::test_pytest_function_names_start_with_test_ PASSED
tests/test_generator.py::test_coverage_notes_are_strings PASSED
...
tests/test_generator.py::test_invalid_json_raises_error PASSED
tests/test_generator.py::test_missing_field_raises_validation_error PASSED

22 passed in 8.34s
```

Key assertions to look for:
- All 22 tests pass (green).
- Total runtime is in the 5-15 second range — confirming only 1 real API call was made (not 20-22).
- The two error-path tests (`test_invalid_json_raises_error`, `test_missing_field_raises_validation_error`) pass, confirming the validation layer works correctly.

### Quick Sanity Check (Python REPL)

```python
from dotenv import load_dotenv
load_dotenv()

from app.generator import generate_test_suite
suite = generate_test_suite("As a user, I want to reset my password via email.")
print(suite.feature)          # Should print a feature name like "Password Reset"
print(len(suite.scenarios))   # Should be between 3 and 7
print(suite.scenarios[0].name)
print(suite.pytest_cases[0].function_name)  # Should start with "test_"
```

---

## 5. Interview Q&A (25 Questions)

---

**Q1. What is this project and what problem does it solve?**

This project is an AI-powered test case generator. It solves a real bottleneck in the software development lifecycle: writing test cases is time-consuming, repetitive, and often skipped under deadline pressure. Developers and QA engineers typically spend 20-60 minutes writing test cases for a single feature. This tool reduces that to under 10 seconds by taking a plain-English user story and using a large language model to generate structured test cases in three industry-standard formats — Gherkin (for BDD frameworks like Cucumber), Pytest (for Python unit testing), and JSON (for integration with test management tools). The output is not perfect but provides a high-quality first draft that engineers refine rather than write from scratch.

---

**Q2. What is OpenRouter and why use it instead of directly calling OpenAI?**

OpenRouter is an API gateway that provides a single, unified endpoint (`https://openrouter.ai/api/v1`) compatible with the OpenAI SDK. Instead of managing multiple API keys and client configurations for different providers, you send all requests to OpenRouter and it routes them to the underlying model — OpenAI, Anthropic, Mistral, Meta, Google, and 200+ others.

Reasons to prefer OpenRouter over direct OpenAI access:
- **Model flexibility:** Switching from `openai/gpt-4o-mini` to `anthropic/claude-3-haiku` requires changing only one string — no new SDK, no new client.
- **Cost comparison:** OpenRouter shows prices for all models side-by-side. `gpt-4o-mini` costs $0.15 per million input tokens, making it very cheap for this use case.
- **Fallback routing:** OpenRouter can automatically fall back to a secondary model if the primary is unavailable.
- **Single billing:** One account, one invoice, access to every major provider.

The OpenAI Python SDK works unchanged with OpenRouter because the API is fully compatible — only the `base_url` changes.

---

**Q3. What is Pydantic and why is it used here?**

Pydantic is a Python library for data validation using type annotations. You define a class that inherits from `pydantic.BaseModel`, annotate its fields with Python types, and when you instantiate it with a dict, Pydantic checks every field against its type and any constraints. If validation fails, it raises a `ValidationError` with a detailed message listing every field that failed.

In this project, Pydantic acts as the contract enforcer between the LLM and the application code. LLMs are probabilistic — they sometimes return slightly wrong field names, wrong types, or missing fields. Without Pydantic, a missing `steps` key might cause a `KeyError` deep inside `suite_to_gherkin()`, making the error message confusing. With Pydantic, the error is caught at the single boundary point where the dict enters the application, with a clear message like: `scenarios.0.steps: field required`. This makes debugging faster and prevents silent data corruption.

---

**Q4. What is structured output / JSON mode in LLMs?**

Structured output refers to instructing an LLM to return its response in a specific machine-readable format — usually JSON — rather than free-form prose. There are two approaches:

1. **Prompt-level instruction (used here):** The system prompt explicitly tells the model to return valid JSON conforming to a specific schema. Simple and universally supported, but relies on the model following instructions consistently.

2. **API-level JSON mode / function calling:** Some APIs (OpenAI, Anthropic) support parameters like `response_format={"type": "json_object"}` or tool/function calling that enforce JSON at the API level, reducing hallucination. This project uses the prompt-level approach for maximum compatibility with any model accessible through OpenRouter.

The tradeoff is that prompt-level JSON mode is less reliable — some models occasionally wrap their JSON in markdown fences or add extra text, which is why `_strip_fences()` exists as a defensive layer.

---

**Q5. What happens if the LLM returns invalid JSON?**

The failure path is:

1. `_strip_fences()` runs first and removes any ``` fences.
2. `json.loads()` attempts to parse the cleaned string. If the string is not valid JSON (e.g., the model returned a sentence instead of a dict), `json.loads()` raises a `json.JSONDecodeError`.
3. This exception propagates up to `streamlit_app.py`, which catches it and displays an error message to the user: *"The AI returned an unexpected format. Please try again."*
4. If JSON parsing succeeds but the structure is wrong (e.g., missing `scenarios` key), `TestSuite.model_validate()` raises a `pydantic.ValidationError`.

Neither error corrupts application state — the user simply sees an error message and can click Generate again. The model-scoped fixture in tests covers this path explicitly with a mock that returns malformed JSON, confirming the error is handled correctly.

---

**Q6. What is `_strip_fences()` and why is it needed?**

`_strip_fences()` is a small utility function in `generator.py` that removes Markdown code fences from a string. A code fence looks like:

````
```json
{ ... }
```
````

The system prompt instructs the LLM to return raw JSON with no fences. However, many LLMs are heavily fine-tuned to wrap code in fences because it looks better in chat interfaces like ChatGPT. This fine-tuning sometimes overrides the system prompt instruction. Rather than fight this with increasingly complex prompts, `_strip_fences()` strips fences as a defensive post-processing step. It uses a regular expression to detect and remove the opening ` ```json ` or ` ``` ` line and the closing ` ``` ` line, leaving only the raw JSON content.

This is an example of defensive programming: assume the dependency (the LLM) will sometimes misbehave in predictable ways, and handle those cases explicitly rather than trusting instructions alone.

---

**Q7. What is a module-scoped pytest fixture and why does it matter here?**

In pytest, a fixture's `scope` parameter controls how often it is created and destroyed. The options are:

| Scope | Created once per... |
|---|---|
| `function` (default) | Each test function |
| `class` | Each test class |
| `module` | Each test file (module) |
| `session` | Entire pytest run |

This project uses `scope="module"` for the fixture that calls the OpenRouter API. This means the fixture runs once when `test_generator.py` is loaded, makes 1 real API call, stores the returned `TestSuite` object, and injects the same object into all 20 tests that declare the fixture as a parameter.

Why it matters: without this, 20 tests would each make their own API call — 20 HTTP round-trips taking 2-5 seconds each means 40-100 seconds of test runtime and 20x the cost. With `scope="module"`, the entire integration test suite runs in about 8 seconds with a single API call. This makes the tests fast enough to run on every commit in CI without significant cost.

---

**Q8. What is the difference between a unit test and an integration test?**

A **unit test** tests a single function or class in complete isolation. All external dependencies (network, databases, other modules) are replaced with mocks or stubs. Unit tests are fast, deterministic, and cheap to run.

An **integration test** tests how multiple components work together, often including real external dependencies. Integration tests catch problems that unit tests miss — for example, a unit test mocking the OpenRouter API might pass even if the real API returns a different JSON structure than the mock does.

In this project:
- The 2 error-path tests (`test_invalid_json_raises_error`, `test_missing_field_raises_validation_error`) are **unit tests** — they mock the OpenAI client and test the error-handling code in isolation.
- The 20 assertion tests are **integration tests** — they call the real OpenRouter API and assert properties of the real response (scenario count, keyword validity, function name format, etc.).

The integration tests provide high confidence that the entire pipeline works end-to-end. The unit tests verify that the error-handling paths work correctly without making real API calls.

---

**Q9. Why not mock the LLM in every test?**

If every test mocked the LLM, the tests would only verify that the code correctly processes *the mock response you wrote*. They would not verify that the real LLM produces output that the code can handle. Over time, the mock might diverge from reality — the LLM could start returning a slightly different structure, the tests would keep passing (because the mock never changes), and the bug would only appear in production.

The integration tests in this project deliberately call the real API to verify that:
1. The real LLM honours the prompt constraints (3-7 scenarios, snake_case, `test_` prefix).
2. The `_strip_fences()` + `json.loads()` + Pydantic pipeline successfully processes real LLM output.
3. The serialisers produce syntactically valid Gherkin and Pytest output from real data.

The cost is managed by the module-scoped fixture (1 API call per test run) and by running tests only in CI (not on every local save).

---

**Q10. What is Gherkin and BDD?**

BDD (Behaviour-Driven Development) is a software development methodology where features are described in plain language that both technical and non-technical stakeholders can read and understand. Gherkin is the language used to write BDD specifications. It follows a strict keyword structure:

```gherkin
Feature: User Login

  Scenario: Successful login with valid credentials
    Given the user is on the login page
    When the user enters valid email and password
    And clicks the login button
    Then the user is redirected to the dashboard
    And a welcome message is displayed
```

Keywords: `Feature`, `Scenario`, `Given` (precondition), `When` (action), `Then` (expected outcome), `And`/`But` (continuation). Gherkin files (`.feature`) are executable by frameworks like Cucumber (Java/JavaScript), Behave (Python), and SpecFlow (.NET) — they link each step to a Python/Java/JS function that implements the actual test logic.

This project generates Gherkin output that is syntactically valid and ready to be executed once a developer writes the step implementations.

---

**Q11. What is a Pytest skeleton/scaffold?**

A Pytest skeleton is a Python file containing test function stubs — functions with the right names, docstrings, and commented-out step descriptions, but with actual assertions left as `pass` or `# TODO`. It gives the developer the structure and a starting point without hallucinating implementation details that might be wrong.

Example output:

```python
def test_login_with_valid_credentials(self):
    """Verify that a user can log in successfully with valid email and password."""
    # Given: the user is on the login page
    # When: the user enters valid credentials
    # Then: the user is redirected to the dashboard
    pass
```

The value is in the naming (correct `test_` prefix, descriptive name in snake_case) and the docstring (which appears in pytest output with `-v`). A developer takes this scaffold, fills in the implementation, and has a properly structured test without the cognitive overhead of deciding what to name it or how to structure the steps.

---

**Q12. What is prompt versioning and why does it matter?**

Prompt versioning is the practice of treating prompts as versioned artifacts — stored in a dedicated location, named explicitly, and changed with the same discipline as code. In this project, `app/prompts.py` contains `SYSTEM_PROMPT_V1` as a named constant.

Why it matters:
- **Auditability:** A git blame on `prompts.py` shows exactly when and why the prompt changed, separate from code changes.
- **Experimentation:** You can add `SYSTEM_PROMPT_V2` and switch between versions with a single import change, enabling A/B testing.
- **Rollback:** If a prompt change degrades output quality, you revert one string in one file.
- **Isolation:** Business logic in `generator.py` does not change when the prompt changes. This is the Single Responsibility Principle applied to AI engineering.

In production AI systems, prompt versioning is as important as model versioning. A seemingly minor wording change ("return JSON" vs "return valid JSON only") can meaningfully change output consistency.

---

**Q13. What is Streamlit and why was it chosen?**

Streamlit is a Python library that turns Python scripts into interactive web applications with no HTML, CSS, or JavaScript required. You write `st.text_area("Enter story")`, `st.button("Generate")`, `st.tabs(["Gherkin", "Pytest", "JSON"])`, and Streamlit renders a fully functional web UI.

It was chosen here because:
- **Speed of development:** Building the same UI in Flask/Django + React would take days. Streamlit took hours.
- **Python-native:** No context switching — the entire stack is Python. The UI code calls Python functions directly.
- **Suitable for demos and portfolios:** Streamlit apps look professional and are easy to share. Streamlit Community Cloud provides free hosting.
- **Trade-offs:** Streamlit is not suitable for production apps with high concurrency or complex state management. Each user interaction re-runs the entire Python script from top to bottom. For a portfolio project or internal tool, these trade-offs are acceptable.

---

**Q14. How would you make this production-ready?**

Several changes would be needed to move from portfolio project to production system:

1. **Authentication:** Add user login (Auth0, Clerk, or Firebase) so only authorised users can generate test cases and costs are attributed per user.
2. **Rate limiting:** Limit each user to N generations per hour/day to control costs and prevent abuse.
3. **Async processing:** For long generations, use a task queue (Celery + Redis) and show a progress spinner rather than blocking the HTTP request.
4. **Error monitoring:** Integrate Sentry to capture and alert on `ValidationError` and `JSONDecodeError` instances — these indicate LLM reliability issues.
5. **Replace Streamlit:** Use FastAPI (backend) + React/Next.js (frontend) for a proper production web app with better state management and concurrency.
6. **Output review workflow:** Add a human review step before the generated tests can be downloaded or committed — AI output should always be reviewed before merging.
7. **Model fallback:** If the primary model is unavailable, fall back to a secondary model automatically using OpenRouter's fallback configuration.
8. **Logging and metrics:** Log every generation event (user, story length, response time, model used, success/failure) for monitoring and cost analysis.
9. **Caching:** Cache responses for identical user stories to avoid duplicate API calls.
10. **Prompt regression testing:** Automated tests that run a fixed set of user stories through the pipeline and compare output quality scores over time, alerting on regressions after prompt changes.

---

**Q15. What are the limitations of AI-generated test cases?**

1. **Semantic incorrectness:** The LLM may generate syntactically valid test cases that test the wrong behaviour. It cannot read your codebase and does not know what your actual implementation does.
2. **Missing edge cases:** The LLM generates plausible-sounding scenarios, but domain-specific edge cases (regulatory requirements, specific error codes, database constraints) require domain knowledge it may not have.
3. **Hallucinated implementation details:** The Pytest skeleton uses placeholder code — the step code may reference functions, variables, or fixtures that do not exist in your project.
4. **Non-determinism:** Running the generator twice on the same story may produce different test cases, making it hard to version or diff AI-generated tests.
5. **Over-reliance risk:** Teams may skip thinking about test coverage because "the AI handled it," leading to a false sense of security.
6. **No integration with code:** The generator does not read the actual source code, so it cannot generate tests that reflect the real function signatures, class names, or data models.

---

**Q16. How do you handle LLM hallucinations?**

This project uses a three-layer defence:

1. **Constrained prompting:** `SYSTEM_PROMPT_V1` uses explicit, specific instructions to narrow the output space. The more constrained the prompt, the less room there is for hallucination.
2. **Defensive parsing:** `_strip_fences()` handles the most common structural hallucination (adding markdown fences) before JSON parsing.
3. **Schema validation:** Pydantic rejects any response that does not conform to the `TestSuite` schema. A `ValidationError` is user-facing and actionable (the user can regenerate).

What remains unhandled: semantic hallucinations (wrong scenarios for the domain), which require human review. The system is designed so that all outputs are clearly labelled as AI-generated drafts requiring review — not ready-to-merge tests.

---

**Q17. Explain the Pydantic model hierarchy for this project.**

```
TestSuite
├── feature: str                    # Feature name (e.g. "User Login")
├── scenarios: list[GherkinScenario]
│   GherkinScenario
│   ├── name: str                   # Scenario title
│   ├── tags: list[str]             # BDD tags (e.g. "@smoke", "@regression")
│   └── steps: list[GherkinStep]
│       GherkinStep
│       ├── keyword: str            # "Given", "When", "Then", "And", "But"
│       └── text: str               # Step description
├── pytest_cases: list[PytestTestCase]
│   PytestTestCase
│   ├── function_name: str          # snake_case, must start with "test_"
│   ├── docstring: str              # One-line description for pytest -v output
│   └── steps: list[PytestStep]
│       PytestStep
│       ├── description: str        # Comment describing the step
│       └── code: str               # Stub code (often "pass" or placeholder)
└── coverage_notes: list[str]       # Human-readable coverage commentary
```

Each model is a standalone Pydantic `BaseModel`. Nesting is automatic — Pydantic recursively validates nested models. The hierarchy mirrors the two output formats (Gherkin and Pytest) plus metadata (`coverage_notes`), all bundled in a single `TestSuite` root object that travels through the entire pipeline.

---

**Q18. What is `coverage_notes` and why is it important?**

`coverage_notes` is a `list[str]` field on `TestSuite` that contains the LLM's own commentary on what is and is not covered by the generated test suite. Examples of what it might contain:

- *"Password complexity rules are not tested — consider adding a scenario for passwords under 8 characters."*
- *"Concurrent login from multiple devices is not covered."*
- *"SQL injection in the email field is not tested — consider security testing."*

This field is important for two reasons:

1. **Transparency:** It signals to the user which gaps the AI is aware of, preventing over-confidence in the generated suite.
2. **Actionability:** It gives the reviewing engineer a checklist of scenarios to consider adding manually.

It also demonstrates a key principle in responsible AI tooling: the system should communicate its own limitations to the user rather than presenting its output as complete and authoritative.

---

**Q19. How would you add a new output format (e.g. Java JUnit)?**

Adding a new output format requires changes in three places:

1. **`app/generator.py`** — Add a new serialiser function:
   ```python
   def suite_to_junit(suite: TestSuite) -> str:
       lines = [
           "import org.junit.jupiter.api.Test;",
           "public class GeneratedTests {",
       ]
       for case in suite.pytest_cases:
           lines.append(f"    @Test")
           lines.append(f"    public void {snake_to_camel(case.function_name)}() {{")
           lines.append(f"        // {case.docstring}")
           lines.append(f"    }}")
       lines.append("}")
       return "\n".join(lines)
   ```

2. **`app/streamlit_app.py`** — Add a fourth tab:
   ```python
   tab1, tab2, tab3, tab4 = st.tabs(["Gherkin", "Pytest", "JSON", "JUnit"])
   with tab4:
       junit_output = suite_to_junit(suite)
       st.code(junit_output, language="java")
       st.download_button("Download JUnit", junit_output, "tests.java")
   ```

3. **`tests/test_generator.py`** — Add assertions about JUnit output validity (class declaration present, `@Test` annotations, method names in camelCase, etc.).

No changes to `models.py` or `prompts.py` are needed, because the same validated `TestSuite` data model can be serialised into any format. This extensibility is a direct result of the clean separation between the data layer (Pydantic models) and the presentation layer (serialiser functions).

---

**Q20. How does CI work without an API key?**

The GitHub Actions workflow file defines a step that exposes the `OPENROUTER_API_KEY` repository secret as an environment variable:

```yaml
env:
  OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

The secret is stored in the repository's Settings → Secrets and Variables → Actions section. It is never stored in the codebase. When the CI runner starts, the secret is injected as an environment variable. `python-dotenv` loads `.env` first, but if `.env` is not present (as is the case in CI — `.env` is in `.gitignore`), the existing environment variable is used instead.

This means: local development uses `.env`, CI uses GitHub Secrets, and the same code path works for both without modification.

---

**Q21. What is the difference between `scope="module"` and `scope="function"` fixtures?**

| | `scope="function"` (default) | `scope="module"` |
|---|---|---|
| Created | Before each test function | Once when the module is first loaded |
| Destroyed | After each test function | After all tests in the module complete |
| API calls (20 tests) | 20 | 1 |
| Cost | 20x | 1x |
| Isolation | Perfect — each test gets fresh data | Shared — all tests see the same object |
| Risk | Tests can never interfere with each other | A test that mutates the fixture object could affect later tests |

For this project, `scope="module"` is the right choice because:
- The `TestSuite` object returned by the fixture is not mutated by any test — tests only read it.
- The cost and speed savings (20x) are significant.
- The test data represents a single real API response, which is what all 20 tests are designed to validate.

---

**Q22. How would you test that the AI generates correct scenarios for different domains?**

Domain coverage testing requires a test matrix approach. The current test module uses a single fixed user story (likely a login or e-commerce scenario). To test across domains:

1. **Parameterised fixtures:** Use `pytest.mark.parametrize` with a list of domain-specific user stories (banking, healthcare, e-commerce, gaming, etc.) and run the full assertion suite against each.

2. **Domain-specific assertions:** For a banking story, assert that at least one scenario mentions "balance" or "transaction". For a login story, assert at least one scenario covers incorrect credentials.

3. **Semantic similarity scoring:** Use an embedding model to compute the cosine similarity between the user story and each generated scenario name. Assert that the average similarity exceeds a threshold.

4. **Manual golden-set review:** Maintain a curated set of 10 user stories with manually written expected scenario categories. Run the generator against them weekly and flag outputs that diverge significantly from the expected categories.

The key insight is that "correct" for AI-generated tests has two dimensions: structural correctness (Pydantic handles this) and semantic relevance (requires domain-aware assertions or human review).

---

**Q23. What would happen if OpenRouter is down?**

The OpenAI Python SDK will raise an `openai.APIConnectionError` or `openai.APIStatusError` (e.g., 503). Currently, this exception propagates up to `streamlit_app.py` and is caught by a generic error handler that shows the user an error message.

Improvements for a production system:
1. **Retry with exponential backoff:** Use `tenacity` to retry up to 3 times with increasing delays before surfacing the error. Most transient outages resolve within 30 seconds.
2. **Fallback model:** Configure OpenRouter to automatically route to a fallback model (e.g., `mistral/mistral-7b-instruct`) if the primary model is unavailable.
3. **Health check endpoint:** Add a `/health` endpoint that pings OpenRouter before accepting user requests, and shows a maintenance banner if the dependency is down.
4. **User-facing error messages:** Replace generic "Something went wrong" with actionable messages: "AI service temporarily unavailable — please try again in a minute."

---

**Q24. How would you add rate limiting or retry logic?**

**Retry logic** using the `tenacity` library:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai

@retry(
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def generate_test_suite(user_story: str) -> TestSuite:
    # existing implementation
    ...
```

This retries up to 3 times on rate limit or connection errors, waiting 2s, 4s, then 8s between attempts.

**Rate limiting** per user (production scenario):

- Store a Redis key per user ID with a counter and TTL: `rate:user:{user_id}`.
- Increment on each request; reject if counter exceeds limit (e.g., 10 per hour).
- Return HTTP 429 with a `Retry-After` header.

For the current Streamlit app (no user accounts), a simpler approach is to add a `time.sleep(1)` between requests and disable the Generate button while a request is in flight (Streamlit handles this with `st.spinner` and button state).

---

**Q25. What metrics would you track in production?**

**Operational metrics (infrastructure health):**
- API response time (p50, p95, p99) — alert if p95 > 10 seconds
- Error rate (ValidationError, JSONDecodeError, APIConnectionError) — alert if > 1%
- OpenRouter API availability — uptime monitoring

**Usage metrics (product health):**
- Generations per day/week — growth trend
- Unique users per day — engagement
- Average scenarios generated per story — output quality proxy
- Download rate — are users actually using the output?

**Cost metrics (financial health):**
- Total OpenRouter spend per day
- Cost per generation (tokens in + tokens out × price)
- Cost per active user

**Quality metrics (AI health):**
- ValidationError rate — increasing rate suggests the model is drifting from the prompt
- Scenarios count distribution — if the average drops below 3, the prompt may need adjustment
- User feedback score (thumbs up/down on generated output) — direct quality signal

These metrics should be stored in a time-series database (Datadog, Grafana + Prometheus, or PostHog for product analytics) and reviewed weekly to catch regressions in model behaviour or cost creep.

---

*This document was generated as a portfolio deep-dive for the `ai-testcase-generator` project. Last updated: May 2026.*
