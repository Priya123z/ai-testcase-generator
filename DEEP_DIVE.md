# Deep dive: ai-testcase-generator

Longer than the README on purpose. The README says what this is for; this says
how it is put together and why each piece is the shape it is.

---

## Contents

1. [What it is, at three levels](#1-what-it-is-at-three-levels)
2. [Architecture](#2-architecture)
3. [Running it](#3-running-it)
4. [Checking it actually works](#4-checking-it-actually-works)
5. [Questions people ask](#5-questions-people-ask)

---

## 1. What it is, at three levels

### Non-technical

You write a sentence describing what a feature should do — *"a registered user
logs in with an email and a password, and the account locks after three failed
attempts."* The tool sends that to a language model and gets back a list of test
cases: the happy path, the wrong password, the empty field, the lockout. Those
come back as two files a tester can use directly — one in Gherkin, the plain
English format teams write acceptance tests in, and one as Python test stubs.

The obvious cases take a person twenty minutes to write down. This does them in
about five seconds, which leaves the twenty minutes for the cases that need
somebody who knows the product.

### How the pipeline works

A small Python library with a Streamlit UI on top and a static browser demo
beside it. Three layers, and the boundaries matter more than the code inside
them.

| File | Role |
|---|---|
| `app/prompts.py` | The system prompt, versioned. Nothing else in the codebase knows what the prompt says. |
| `app/generator.py` | Provider selection, retries, fence stripping, JSON parse, and the two serialisers. |
| `app/models.py` | The Pydantic contract. Everything the model returns passes through here. |
| `app/streamlit_app.py` | The local UI. Imports the library; holds no generation logic of its own. |
| `site/` | The published browser demo. Calls Groq directly from the page; no server. |
| `tests/test_generator.py` | 22 tests — 20 integration against a live model, 2 contract tests that patch the network. |
| `tests/test_browser_parity.py` | 3 tests pinning the JavaScript serialisers to the Python ones. |

The path a request takes:

1. A story arrives as free text.
2. `available_providers()` returns the providers that have a key, in order:
   Groq first, OpenRouter behind it. A key passed as an argument is treated as a
   Groq key and used on its own — that is the path the UI uses when a visitor
   brings their own.
3. `_generate_with()` builds an `openai.OpenAI` client pointed at that provider's
   base URL. Both speak the OpenAI wire format, so one client class covers both.
   The request asks for `response_format={"type": "json_object"}`.
4. The reply is stripped of markdown fences, parsed as JSON, and validated into
   a `TestSuite`.
5. `suite_to_gherkin` and `suite_to_pytest` turn that object into two text files.

Each provider gets three attempts before the chain moves on. If every provider
fails, the error names each attempt rather than reporting a bare failure.

### The design decisions

**The Pydantic step is the point of the project.** A model that returns
*almost*-right JSON — a scenario with no steps, a keyword that is not a Gherkin
keyword, a missing `coverage_notes` — produces a `.feature` file that fails to
parse in somebody's CI three days later, and the traceback names the parser
rather than the generator. Validating at the boundary turns that into a
`ValidationError` at the point of the mistake. The cost is one module of model
classes. It is worth it.

**Prompts live in one file and are versioned.** `SYSTEM_PROMPT_V1` and
`SYSTEM_PROMPT_VERSION`. Changing review strategy is a one-file diff, and no
module above it knows what the prompt says. It also means the browser demo can
carry a copy without importing Python.

**Two providers, three attempts each.** Free tiers rate limit without warning.
Groq is primary because its free tier allows 1000 requests a day against
OpenRouter's 50, and it supports a real JSON mode rather than a request to
please answer in JSON. The retry inside a provider is not paranoia: the schema
asks the model to nest generated Python inside JSON strings, and a model
occasionally emits a stray brace that strict JSON mode rejects. Sampling again
usually produces valid output. That is a property of the model, not of the
prompt, so retrying is the correct response rather than prompt-tweaking.

**Streamlit is in a separate requirements file.** Only `app/streamlit_app.py`
imports it. Pulling a web framework in to run a test suite that never touches
one is a slow install for nothing, so `requirements.txt` is the library and the
tests, and `requirements-ui.txt` adds Streamlit on top.

**The browser demo duplicates two functions, deliberately.** `site/app.js`
reimplements `suite_to_gherkin` and `suite_to_pytest` in JavaScript, because
that page calls Groq straight from the browser and has no Python to call. Real
duplication is a real risk, so `tests/test_browser_parity.py` extracts both
functions out of `app.js`, runs them under Node over the same suite, and
requires byte-identical output.

---

## 2. Architecture

```
                        A requirement, in plain English
                                      |
        +-----------------------------+-----------------------------+
        |                             |                             |
        v                             v                             v
  streamlit_app.py              generate_test_suite()          site/app.js
  (local UI)                    (library entry point)          (browser demo)
        |                             |                             |
        +--------------+--------------+                             |
                       |                                            |
                       v                                            |
             available_providers()                                  |
               Groq  ->  OpenRouter                                 |
               3 attempts each                                      |
                       |                                            |
                       v                                            v
              openai.OpenAI client                       fetch() straight to
              response_format=json_object                api.groq.com
                       |                                            |
                       v                                            v
                 _strip_fences()                             JSON.parse()
                 json.loads()                                        |
                       |                                            v
                       v                                     validate() in JS
             TestSuite.model_validate()                    (the same rules)
                       |                                            |
        +--------------+--------------+                             |
        |                             |                             |
        v                             v                             |
  suite_to_gherkin()          suite_to_pytest()   <------------------+
        |                             |            (toGherkin / toPytest,
        v                             v             pinned byte-for-byte by
   Feature file                 Pytest module       test_browser_parity.py)
```

### The model hierarchy

```
TestSuite
  feature         : str
  scenarios       : list[GherkinScenario]
  |                   name  : str
  |                   tags  : list[str]
  |                   steps : list[GherkinStep]
  |                             keyword : str   Given / When / Then / And
  |                             text    : str
  pytest_cases    : list[PytestTestCase]
  |                   function_name : str
  |                   docstring     : str
  |                   steps         : list[PytestStep]
  |                                     description : str
  |                                     code        : str
  coverage_notes  : str
```

Nesting mirrors the shape of the thing being described rather than flattening it
for convenience. A scenario owns its steps; a step is a keyword and a sentence.
When the model returns a step as a bare string instead of an object, validation
fails on that field and names it, which is the behaviour you want.

`TestSuite` carries `__test__ = False`. It is a model, not a test class, but
pytest collects anything matching `Test*` that it finds in a test module's
namespace and used to warn about it on every run.

### Where the layers stop

- `models.py` imports only Pydantic. It knows nothing about providers or HTTP.
- `prompts.py` imports nothing at all.
- `generator.py` is the only module that makes a network call.
- `streamlit_app.py` imports the library and adds no generation logic.

So the library is usable without Streamlit, the prompts are editable without
touching the library, and the models can be reused by anything.

---

## 3. Running it

### Prerequisites

- Python 3.11 or newer
- A free Groq API key — [console.groq.com/keys](https://console.groq.com/keys),
  about a minute, no card
- Node, only if you want the two browser-parity tests to run rather than skip

### Steps

```bash
git clone https://github.com/Priya123z/ai-testcase-generator.git
cd ai-testcase-generator

python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate

# The library and its tests
pip install -r requirements.txt

# Configure a key
cp .env.example .env
# then put your key in it:
#   GROQ_API_KEY=gsk_your_key_here
```

As a library:

```python
from app.generator import generate_test_suite, suite_to_gherkin, suite_to_pytest

suite = generate_test_suite(open("examples/login_story.txt").read())
print(suite_to_gherkin(suite))
```

As a local app:

```bash
pip install -r requirements-ui.txt      # adds streamlit on top
streamlit run app/streamlit_app.py      # http://localhost:8501
```

In a browser, with nothing installed:
[priya123z.github.io/ai-testcase-generator](https://priya123z.github.io/ai-testcase-generator/).
With no key it shows a saved answer from a real run, labelled as saved. Paste a
key and the same story runs live, in the tab, against Groq — there is no server
in that path, so nothing is proxied and nothing is stored.

### What each dependency is for

| Package | Why |
|---|---|
| `openai` | The client. Points at Groq or OpenRouter by base URL; both speak this wire format. |
| `pydantic` | The validation boundary. The reason a bad answer fails here rather than downstream. |
| `python-dotenv` | Reads `GROQ_API_KEY` out of `.env` so a key never has to be pasted into a shell. |
| `pytest` | The suite. |
| `streamlit` | `requirements-ui.txt` only. The local UI. |

---

## 4. Checking it actually works

### On a clean clone, with no key

```bash
pytest
```

Expect **5 passed, 20 skipped**. That is the whole point of the split: the
contract tests and the parity tests need no network, so cloning the repo and
running pytest works for someone who has never heard of Groq. The 20 skips name
their reason (`no GROQ_API_KEY or OPENROUTER_API_KEY set`).

If Node is missing, two of those five skip as well and you get 3 passed.

### With a key

```bash
GROQ_API_KEY=gsk_... pytest
```

Expect **25 passed**, in roughly seven seconds. All twenty integration tests
share a single API call through a module-scoped fixture.

### What the integration tests assert

Not exact text. The output is not deterministic, and a suite that pins exact
strings against a live model fails for no reason and gets ignored within a week.
They assert properties that must hold for any sensible answer:

- between three and seven scenarios
- every scenario has a name and at least one step
- every step keyword is one of Given / When / Then / And / But
- every pytest function name is snake_case and starts with `test_`
- the feature name and every scenario name appear in the rendered Gherkin
- the rendered pytest starts with `import pytest` and defines every function

### A sanity check by hand

```python
>>> from app.generator import generate_test_suite, suite_to_gherkin
>>> suite = generate_test_suite("A user resets their password by email link. The link expires after 30 minutes.")
>>> len(suite.scenarios)
5
>>> print(suite_to_gherkin(suite))
Feature: Password reset by email
  @happy_path
  Scenario: Reset link sent to a registered address
    Given ...
```

If that returns a `TestSuite` and the Gherkin parses, the pipeline is intact end
to end.

### In CI

`.github/workflows/tests.yml` passes both provider keys through as secrets. With
them, all 25 run. Without them — a fork, for instance — the 20 integration tests
skip and the build is still green. That is the split doing its job rather than a
gap in coverage.

`.github/workflows/pages.yml` publishes `site/` and, before it does, revalidates
`site/samples/login.json` against the same rules the page enforces. The no-key
path is what most visitors see; if that file ever drifted from what the page
expects, the demo would render nothing and no test would have noticed.

---

## 5. Questions people ask

**Q1. What problem does this solve?**

Test design starts with a blank page, and most of what goes on that page is
obvious. Writing down the obvious cases is slow, and it consumes the attention
that should go to the two cases that are not obvious. This writes the obvious
ones so a person can spend their twenty minutes on the rest. It is a starting
point for review, not a replacement for test design.

**Q2. Why Groq, and why an OpenAI client pointed at it?**

Groq exposes an OpenAI-compatible endpoint, so one client class covers both
providers and switching is a base URL. Groq is first because its free tier
allows 1000 requests a day against OpenRouter's 50, it supports a genuine JSON
mode rather than a polite request, and it answers in well under a second.
OpenRouter sits behind it because free tiers go quiet without warning, and one
provider is not enough to keep a public demo working.

**Q3. Why Pydantic rather than checking the dict by hand?**

Because the checks would be spread across the codebase and would drift. One
model class states the contract once, in a form that is also the documentation,
and raises at the boundary with the offending field named. It also gives
`model_dump()` for the JSON tab and `model_validate()` for the parse, which
would otherwise be hand-written.

**Q4. What is JSON mode, and does it make the parsing safe?**

`response_format={"type": "json_object"}` constrains the model to emit
syntactically valid JSON. It guarantees *syntax*, not *shape* — you can still
get valid JSON with a missing field or a scenario with no steps. So JSON mode
removes one failure class and Pydantic removes the other. Both are needed.

**Q5. What happens when the model returns invalid JSON anyway?**

`json.loads` raises, `_generate_with` turns it into a `ValueError("invalid
JSON: ...")`, and `generate_test_suite` records that attempt and tries again —
up to three times per provider, then the next provider. If everything fails, the
`RuntimeError` lists every attempt and its reason rather than saying the request
failed. In the UI that becomes a message telling you free tiers rate limit and
that your own key in the sidebar usually clears it.

**Q6. What is `_strip_fences` for?**

Some models wrap JSON in a markdown code fence despite being told not to, and
JSON mode does not always prevent it. Three lines of regex here is cheaper than
a retry, and it runs before `json.loads` so the common case never becomes an
error at all.

**Q7. Why is the live fixture module-scoped?**

Twenty tests, one call. `scope="module"` runs the fixture once, holds the
`TestSuite`, and injects the same object into every test that asks for it.
Function scope would mean twenty HTTP round trips at two to five seconds each —
a minute and a half of runtime and twenty times the quota, to assert twenty
different things about output that would not even be the same output. Sharing
one answer is also more correct: the assertions are about a single response
being internally consistent.

**Q8. Unit test or integration test — which are these?**

Both, deliberately. The two error-path tests are unit tests: they patch
`openai.OpenAI` and exercise the error handling with no network. The twenty
assertion tests are integration tests against a real provider, which is the only
way to catch a real API returning a different shape than a mock says it does.
The parity tests are a third thing again — they run one implementation against
another and require identical output.

**Q9. Why not mock everything?**

A mock asserts that the code matches your belief about the API. It cannot tell
you the belief is wrong. Providers change model behaviour, deprecate slugs and
alter how JSON mode behaves, and a fully mocked suite stays green through all of
it. The split keeps the fast, always-runnable half separate from the half that
tells you the truth.

**Q10. What is Gherkin, and why emit it?**

Gherkin is the Given/When/Then format BDD tools read — `pytest-bdd`, `behave`,
Cucumber. It is the format a non-engineer on the team can read and correct,
which matters more here than usual: the output needs reviewing, so it should be
reviewable by whoever knows the product.

**Q11. What is the pytest half for, if the Gherkin is the readable one?**

The Gherkin describes the intent; the pytest module is where the work goes. Each
case comes back as a function with a docstring and commented steps, so the
skeleton says what each line is supposed to do and someone fills in the calls.
It is a starting file rather than an empty one.

**Q12. Why version the prompt?**

Because prompt changes are the highest-variance change in a project like this,
and the only way to reason about a regression is to know which prompt produced
which output. `SYSTEM_PROMPT_V1` plus `SYSTEM_PROMPT_VERSION` means a stored
result can be attributed, and a new strategy is `_V2` beside it rather than an
edit that erases the old behaviour.

**Q13. Why Streamlit, and why is it optional?**

Streamlit gets a working form, tabs and download buttons out of about a hundred
lines with no frontend. It is the right tool for a local app that one team uses.
It is optional because the library does not need it and neither do the tests —
so it lives in `requirements-ui.txt`, and `pip install -r requirements.txt` stays
fast.

**Q14. There is a browser version too. Why does it duplicate the serialisers?**

The published page calls Groq straight from the visitor's browser, with a key
they paste in. That is the best possible privacy story — no server, nothing
proxied, the key gone when the tab closes — and the cost is that there is no
Python in that path. So `toGherkin` and `toPytest` are reimplemented in
JavaScript. Rather than hope they stay in step, `tests/test_browser_parity.py`
pulls both functions out of `site/app.js`, runs them under Node against the same
sample, and requires byte-identical output. The duplication is real, so it is
pinned rather than denied.

**Q15. What are the limitations of the generated cases?**

It is good at the happy path and the obvious negative paths and it misses
anything that depends on domain knowledge. It has never seen your billing rules,
so it will write a confident, plausible, wrong scenario about proration. Two runs
on the same story will differ. Every answer carries `coverage_notes` saying what
it left out, and that field is worth reading before the scenarios.

**Q16. How do you handle hallucination?**

By separating the two kinds. Structural hallucination — an invented field, a
malformed step — is caught by Pydantic and cannot reach you. Semantic
hallucination — a scenario that is well-formed and wrong — cannot be caught
automatically, and pretending otherwise would be the real failure. The honest
answer is that this is why the output is a draft for review, and why
`coverage_notes` is a required field rather than an optional one.

**Q17. What is `coverage_notes` for?**

It forces the model to say what it did *not* cover. That turns out to be the
most useful field in the response: it is where you find out that session
management, MFA and rate limiting were considered and left out. It is also a
good teaching device for someone new to test design, because it makes the
scoping decision explicit rather than invisible.

**Q18. How would you add a new output format, say JUnit?**

Add `suite_to_junit(suite)` next to the other two serialisers. Nothing else
changes: the model layer, the prompt and the provider logic are all unaware of
output formats, and the two existing serialisers are pure functions over a
`TestSuite`. Then a tab in the Streamlit app and, if it should appear in the
browser demo, a mirrored JavaScript function and a third parity test.

**Q19. How does CI stay green without an API key?**

Because the suite is split and the split is enforced by a skip marker, not by
convention. `HAS_KEY` is computed once at import; `needs_key` skips the
integration tests with a stated reason. A fork gets 5 passed, 20 skipped, and a
green build. Adding `GROQ_API_KEY` as a repository secret is all it takes to turn
the other twenty on.

**Q20. What happens if a provider is down?**

Three attempts, then the next provider, then a `RuntimeError` naming every
attempt. In the Streamlit UI that is caught and shown with the suggestion to
paste your own key. On the published page there is no fallback provider at all —
it is browser-to-Groq — so a failure there falls back to the saved answer, which
is labelled as saved rather than passed off as live. A demo that shows an error
teaches a visitor nothing; a demo that lies about being live is worse.

**Q21. `scope="module"` versus `scope="function"` — what actually changes?**

Function scope creates the fixture fresh per test; module scope creates it once
per module and shares it. Sharing is right when the object is expensive and the
tests do not mutate it, which is exactly this case. It would be wrong if any
test modified the suite, because the mutation would leak into the tests that ran
after it — worth stating, because that is the failure mode module scope invites.

**Q22. How would you check it generates good scenarios across different domains?**

Property assertions do not measure quality, only well-formedness. To measure
quality you would need a labelled set — a handful of stories with a
human-written list of the cases that must appear — and score recall against it
per prompt version. That is the experiment that would justify a `_V2`. It is not
in the repo, and claiming the current suite measures quality would be wrong.

**Q23. How would you add rate limiting or backoff?**

The retry loop in `generate_test_suite` is the place: it already catches per
attempt, so it needs a sleep between attempts and a check for a 429 to
distinguish "wait" from "this will never work". Right now it retries everything
equally, which is fine at three attempts against a free tier and would not be
fine at scale. Above that, a token bucket in front of the call, and the response
cache the sibling project uses — two people pasting the same story is the common
case for anything linked from a portfolio, and a cache hit costs no quota at all.

**Q24. What would you monitor if this ran in production?**

Operationally: latency per provider, which provider served each request, attempt
counts, and the rate of validation failures — that last one is the leading
indicator of a model or prompt regression, because it rises before anyone
notices the output got worse.

On quality: scenarios per story against the requested three-to-seven, how often
`coverage_notes` comes back empty, and, if you have the labelled set from Q22,
recall against it per prompt version. Plus the only metric that really matters —
how much of a generated suite survives review unedited.

**Q25. What would you change if this became a real product?**

Persist the results, so a prompt change can be compared against previous output
instead of remembered. Put the labelled evaluation set in and gate prompt changes
on it. Move the provider chain and the retry logic out of `generate_test_suite`
into something reusable, since it is the same logic as the sibling project's and
neither knows about the other. And take the browser demo's duplicated serialisers
seriously — either generate the JavaScript from the Python, or accept the
duplication permanently and keep the parity test, which is what happens today.

---

MIT. Built by Priya Bhagoriya — [portfolio](https://priya123z.github.io/) ·
[LinkedIn](https://linkedin.com/in/priya-bhagoriya)
