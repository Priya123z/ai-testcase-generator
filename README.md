# AI Test-Case Generator

Paste a requirement in plain English. Get back Gherkin scenarios and Pytest
skeletons you can drop into a suite.

[![Tests](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)
![Model](https://img.shields.io/badge/model-gpt--oss--120b%20on%20Groq-0a6e4e.svg)

[**Try it in a browser**](https://priya123z.github.io/ai-testcase-generator/) — no install, no server, runs on your own free key.

---

## When you would actually reach for this

The honest answer is: at the start of test design, not instead of it.

- **A story lands in refinement and you have twenty minutes.** Paste the
  acceptance criteria and you get a first list of scenarios. Most will be
  obvious; the value is that the obvious ones are already written down and you
  can spend your twenty minutes on the two that are not.
- **You are reviewing someone else's test plan.** Run the same story through
  this and diff the two lists. What the model found and the plan missed is
  usually worth a conversation.
- **You inherited an untested module with a written spec.** This turns the spec
  into a skeleton you can fill in, which is a much easier place to start than an
  empty file.
- **Onboarding a junior tester.** The `coverage_notes` field says what it chose
  *not* to cover, which is a decent teaching device.

Where **not** to use it: anything where the edge cases come from domain
knowledge rather than the text. It has never seen your billing rules. It will
write a plausible-looking scenario about proration and get it wrong.

---

## How it works

```
Requirement (plain text)
        |
   Groq: openai/gpt-oss-120b, JSON mode
        |  falls back to OpenRouter if Groq is unavailable
   Pydantic TestSuite validation
        |  invalid structure raises here, not three files later
   Gherkin .feature  |  Pytest .py  |  raw JSON
```

1. Paste a requirement with its acceptance criteria.
2. The model writes 3–7 scenarios — happy path, negative paths, edge cases —
   and a matching Pytest function skeleton for each.
3. `TestSuite` validates every field. A hallucinated structure is rejected
   before it reaches you, so you never get a `.feature` file that will not
   parse.
4. Download the `.feature` or the `.py`, or copy the JSON.

The Pydantic step is the part that makes this usable rather than a toy. A model
that returns almost-right JSON produces test files that fail in confusing ways
much later; failing at the boundary is worth the extra class.

---

## Example output

From the login story in `examples/login_story.txt`:

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

## Three ways to run it

**1. In your browser, nothing installed.**
[priya123z.github.io/ai-testcase-generator](https://priya123z.github.io/ai-testcase-generator/)
is a static page that calls Groq directly with a key you paste in. There is no
server in that path, so nothing is proxied, nothing is stored, and the key is
gone when the tab closes. With no key it shows a saved answer from a real run.

**2. As a library.**

```bash
git clone https://github.com/Priya123z/ai-testcase-generator.git
cd ai-testcase-generator

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

```python
from app.generator import generate_test_suite, suite_to_gherkin, suite_to_pytest

suite = generate_test_suite(open("examples/login_story.txt").read())
print(suite_to_gherkin(suite))
```

**3. As a local app**, for a team that wants a form rather than an import:

```bash
pip install -r requirements-ui.txt
cp .env.example .env          # then put a Groq key in it, see below
streamlit run app/streamlit_app.py
```

Open http://localhost:8501, paste a requirement, press **Generate**.

`streamlit` is in `requirements-ui.txt` rather than `requirements.txt` on
purpose — only `app/streamlit_app.py` imports it, and pulling a web framework in
order to run a test suite that never touches one is a slow install for nothing.

## Getting a key

Groq is the primary provider. A free key takes about a minute and needs no card:

1. Sign in at [console.groq.com/keys](https://console.groq.com/keys)
2. **Create API Key**, copy it (starts with `gsk_`)
3. Put it in `.env`:

```
GROQ_API_KEY=gsk_your_key_here
```

The free tier allows 1000 requests a day and supports a real JSON mode, which
is why it is the default. If you also set `OPENROUTER_API_KEY` it is tried when
Groq is unavailable. Free tiers rate limit without warning, which is why there
is a fallback and why each provider gets a few attempts.

Override the model per call:

```python
suite = generate_test_suite(story, model="llama-3.3-70b-versatile")
```

---

## Tests

The suite splits in two, deliberately.

**Contract tests** patch the network. They pin the shaping and serialising logic
and run anywhere with no key, so `pytest` works on a fresh clone.

**Integration tests** call a real model. They skip when no key is set. They
assert on properties that hold for *any* sensible answer — step keywords are
valid Gherkin, function names are snake_case, scenario count is in range —
rather than on exact text, because the output is not deterministic. Asserting on
exact strings against a live model gives you a suite that fails for no reason.
All twenty share one API call.

There is a third group: the browser demo reimplements the two serialisers in
JavaScript, because that page has no Python to call. Real duplication, so it is
pinned — `tests/test_browser_parity.py` runs both implementations over the same
suite and requires byte-identical output. It skips when `node` is absent, so a
clean clone still passes.

```bash
pytest                        # no key:   5 passed, 20 skipped
GROQ_API_KEY=gsk_... pytest   # with key: 25 passed
```

Last runs: **25 passed in 7.4s** with a key, **5 passed / 20 skipped** on a
clean clone with none. CI on the last commit: **22 passed**, integration tests
included.

### Making CI run the live tests

CI passes both `GROQ_API_KEY` and `OPENROUTER_API_KEY` through to pytest. Add
either as a repository secret and the integration tests start running:

1. Repo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**, name it `GROQ_API_KEY`

Without it the integration tests skip and the contract tests still pass, so the
build stays green on a fork with no access to secrets. That is the point of the
split.

---

## Prompt versioning

`app/prompts.py` holds versioned system prompts (`SYSTEM_PROMPT_V1`). Changing
prompt strategy is a one-file change — nothing else in the codebase knows what
the prompt says — so you can iterate on quality without touching modules.

---

## Honest caveats

Generated tests are a starting point for review, not a replacement for test
design. It is good at the happy path and the obvious negative paths, and it
misses edge cases that need business context. Every answer carries a
`coverage_notes` field that says what it left out; read it.

Two runs on the same requirement will differ. That is the nature of the thing,
and it is why the tests assert on properties rather than output.

---

## Layout

```
ai-testcase-generator/
|- app/
|  |- generator.py        provider fallback, retries, JSON parse, serialisers
|  |- models.py           Pydantic models (TestSuite, GherkinScenario, ...)
|  |- prompts.py          versioned system prompts
|  '- streamlit_app.py    the web UI
|- site/                  the browser demo, published to GitHub Pages
|  |- index.html
|  |- app.js              talks to Groq directly; mirrors the two serialisers
|  |- style.css
|  '- samples/login.json  a real answer, shown when there is no key
|- tests/
|  |- test_generator.py       22 tests: 2 contract, 20 integration
|  '- test_browser_parity.py  3 tests: the JS and Python output must match
|- examples/
|  |- login_story.txt
|  '- checkout_story.txt
|- .github/workflows/
|  |- tests.yml
|  '- pages.yml           publishes site/
|- .env.example
|- requirements.txt       library + tests
'- requirements-ui.txt    adds streamlit
```

MIT. Built by Priya Bhagoriya — [portfolio](https://priya123z.github.io/) · [LinkedIn](https://linkedin.com/in/priya-bhagoriya)
