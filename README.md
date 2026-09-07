# AI Test-Case Generator

Paste a requirement in plain English. Get back Gherkin scenarios and Pytest
skeletons you can drop into a suite.

[![Tests](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/Priya123z/ai-testcase-generator/actions/workflows/tests.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)
![Model](https://img.shields.io/badge/model-gpt--oss--120b%20on%20Groq-0a6e4e.svg)

[**Try it in a browser**](https://priya123z.github.io/ai-testcase-generator/): no install, no signup, no key needed.

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
   check_suite()
        |  invalid structure raises here, not three files later
   Gherkin .feature  |  Pytest .py  |  raw JSON
```

1. Paste a requirement with its acceptance criteria.
2. The model writes between three and seven scenarios covering the happy path,
   the negative paths and the edge cases, with a matching Pytest function
   skeleton for each.
3. `check_suite` rejects it if a field is missing, a step keyword is not
   Gherkin, a docstring is blank, or a function name is one pytest will never
   collect. So you never get a `.feature` file that will not parse, or a test
   module that collects nothing, or the word `undefined` where a docstring
   should be.
4. Download the `.feature` or the `.py`, or copy the JSON.

That check is the part that makes this usable rather than a toy. A model that
returns almost-right JSON produces test files that fail in confusing ways much
later; failing at the boundary is worth twenty lines. The browser demo runs the
same checks in JavaScript, so both paths accept exactly the same answers.

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

## Two ways to run it

**1. In your browser, nothing installed.**
[priya123z.github.io/ai-testcase-generator](https://priya123z.github.io/ai-testcase-generator/)
is a static page, and you do not need a key to use it. The request goes to a
small Cloudflare Worker holding my Groq key as a secret, inside a daily budget
of 400 runs across everyone and 12 per visitor. That Worker lives in the
[portfolio repository](https://github.com/Priya123z/Priya123z.github.io/tree/main/worker)
and serves both pages, since this one is a project page on the same origin.

Paste your own key instead and the browser calls Groq directly, with nothing of
mine in the path and nothing stored. If the budget is spent or Groq is having a
bad afternoon, you get a saved answer from a real earlier run, and the page says
which of the three happened rather than passing one off as another.

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

## Getting a key

Groq is the primary provider. A free key takes about a minute and needs no card:

1. Sign in at [console.groq.com/keys](https://console.groq.com/keys)
2. **Create API Key**, copy it (starts with `gsk_`)
3. Put it in `.env`:

```
GROQ_API_KEY=gsk_your_key_here
```

Groq's free tier supports a real JSON mode, which is why it is the default. Its
published limits are 30 requests a minute and 1000 a day, but requests are not
what runs out. **Tokens are: 8,000 a minute and 200,000 a day.** One generated
suite costs roughly 3,000 tokens, so the real ceiling is about sixty runs a day
and two or three a minute, nowhere near a thousand.

That is worth knowing before you point a test suite at it. Running this
repository's integration tests repeatedly will exhaust a day's tokens, and when
that happens every model on the key returns 429 and the integration tests error
rather than skip. Nothing is wrong; the budget is simply spent until it resets.

Set `OPENROUTER_API_KEY` as well and it is tried when Groq is unavailable. It is
the only thing that helps once a Groq day is spent.

Within Groq, a rate-limited model is not retried: asking the same model again
inside the same minute cannot succeed, so the next smaller model is tried
instead, `gpt-oss-20b` and then `qwen3.8-27b`. A model that returns malformed
JSON *is* retried once, because resampling usually fixes that. The two failures
need opposite responses, which is why they are told apart.

Override the model per call. It has to be a slug the provider still serves and
that supports JSON mode, so check
[Groq's model list](https://console.groq.com/docs/models) rather than trusting an
example: this one named a model Groq had retired, and the call came back 404.

```python
suite = generate_test_suite(story, model="openai/gpt-oss-20b")
```

---

## Tests

The suite splits in two, deliberately.

**Contract tests** patch the network. They pin the shaping and serialising logic
and run anywhere with no key, so `pytest` works on a fresh clone.

**Integration tests** call a real model and skip when no key is set. They assert
on properties that hold for *any* sensible answer: step keywords are valid
Gherkin, function names are snake_case, the scenario count is in range. Not on
exact text, because the output is not deterministic, and asserting on exact
strings against a live model gives you a suite that fails for no reason. All
nineteen share one API call.

There is a third group, and it is the one worth reading. The browser demo carries
its own copy of the system prompt, of the two serialisers, and of the validator,
because that page has no Python to call. `tests/test_browser_parity.py` pins all
three.

The prompt is compared character for character, and the serialisers are run over
the same suite and required to produce byte-identical output. The validator is
pinned differently, by behaviour: both copies are fed the same fourteen malformed
suites and have to agree on every one. Comparing their source would prove
nothing, because they are not meant to read alike, only to decide alike.

Neither check is hypothetical. The two prompts had already drifted, and the
JavaScript one had lost the clause telling the model to name what it chose *not*
to cover, so the same requirement produced measurably different output depending
on which path a visitor took. And the validators had drifted three ways: the
JavaScript accepted a suite with no coverage notes, one with a step that had no
text, and one with no Pytest cases at all. Each of those reaches a visitor as a
half-empty answer rather than an error. Nothing was comparing them. Now something is.

```bash
pytest                        # no key:            21 passed, 19 skipped
GROQ_API_KEY=gsk_... pytest   # with key:          40 passed
                              # without node too:   4 passed, 36 skipped
```

Everything that runs JavaScript needs `node` and skips without it, so a clean
clone still passes either way. The prompt comparison needs nothing and always
runs. CI installs node, so the parity this advertises is actually enforced there
rather than quietly skipped.

### Making CI run the live tests

CI passes both `GROQ_API_KEY` and `OPENROUTER_API_KEY` through to pytest. Add
either as a repository secret and the integration tests start running:

1. Repo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**, name it `GROQ_API_KEY`

Without it the integration tests skip and the contract tests still pass, so the
build stays green on a fork with no access to secrets. That is the point of the
split.

---

## Where the prompt lives

`app/prompts.py` holds it, as `SYSTEM_PROMPT_V1`. Nothing else in the Python
codebase knows what the prompt says, so changing strategy is a one-file change
and you can iterate on quality without touching modules.

The one exception is `site/app.js`, which needs its own copy because the browser
has no Python to import. Change the prompt and you have to change both, and
`tests/test_browser_parity.py` fails until you do.

---

## Honest caveats

Generated tests are a starting point for review, not a replacement for test
design. It is good at the happy path and the obvious negative paths, and it
misses edge cases that need business context. Every answer carries a
`coverage_notes` field that says what it left out; read it.

The daily budget behind the no-key path lives in the Worker, in the portfolio
repository, not here. This repository cannot change it or report on it.

Two runs on the same requirement will differ. That is the nature of the thing,
and it is why the tests assert on properties rather than output.

---

## Layout

```
ai-testcase-generator/
|- app/
|  |- generator.py        providers, retries, JSON parse, check_suite, serialisers
|  '- prompts.py          the system prompt
|- site/                  the browser demo, published to GitHub Pages
|  |- index.html
|  |- app.js              talks to Groq directly; mirrors the two serialisers
|  |- style.css
|  '- samples/login.json  a real answer, shown when there is no key
|- tests/
|  |- test_generator.py       21 tests: 2 contract, 19 integration
|  '- test_browser_parity.py  19 tests: the JS and Python copies must match
|- examples/login_story.txt   the story the integration tests use
|- .github/workflows/
|  |- tests.yml
|  '- pages.yml           publishes site/
|- .env.example
'- requirements.txt
```

MIT. Built by Priya Bhagoriya: [portfolio](https://priya123z.github.io/) · [LinkedIn](https://linkedin.com/in/priya-bhagoriya)
