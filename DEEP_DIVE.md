# A deep read of ai-testcase-generator

The README says what this is for and how to run it. This is the long version:
how it is put together, why each piece is the shape it is, what the tests
actually assert, and the questions people ask when they review it.

- [1. What it is](#1-what-it-is)
- [2. Every file, and why it exists](#2-every-file-and-why-it-exists)
- [3. One call, end to end](#3-one-call-end-to-end)
- [4. The models, and why validation sits at the boundary](#4-the-models-and-why-validation-sits-at-the-boundary)
- [5. The provider chain](#5-the-provider-chain)
- [6. The serialisers](#6-the-serialisers)
- [7. The prompt](#7-the-prompt)
- [8. Three surfaces, one library](#8-three-surfaces-one-library)
- [9. The browser demo, and its duplication](#9-the-browser-demo-and-its-duplication)
- [10. Testing something that answers differently every time](#10-testing-something-that-answers-differently-every-time)
- [11. CI](#11-ci)
- [12. Running it yourself](#12-running-it-yourself)
- [13. Decisions, and the ones worth arguing about](#13-decisions-and-the-ones-worth-arguing-about)
- [14. What it does not do](#14-what-it-does-not-do)
- [15. FAQ](#15-faq)

---

## 1. What it is

### If you do not write software

You write a sentence describing what a feature should do. *"A registered user
logs in with an email and a password, and the account locks after three failed
attempts."*

A tester's job is then to turn that sentence into a list of things to check. The
obvious ones: does a correct password work, does a wrong one fail, what happens
on the third wrong one, what if the box is empty. Writing that list down takes
maybe twenty minutes, and most of it is mechanical.

This tool sends the sentence to a language model and gets the list back in about
five seconds, in two formats a tester can use straight away. That does not
replace the twenty minutes. It moves them to the two or three cases that need
somebody who actually understands the product, which is where the twenty minutes
were always worth spending.

### If you write software

A small Python library. One function in, one validated object out:

```python
suite = generate_test_suite("As a user I want to log in...")
print(suite_to_gherkin(suite))
print(suite_to_pytest(suite))
```

`generate_test_suite` calls a model with a fixed system prompt, asks for JSON,
parses it, and validates the result against a Pydantic model before returning.
`suite_to_gherkin` and `suite_to_pytest` turn that object into files.

Three surfaces sit on top: import it as a library, run it as a Streamlit app, or
use the static browser page, which needs nothing installed and no key.

### If you are reviewing the design

The whole project is one idea worked through: **model output is untrusted input,
and it should be validated at the boundary like any other untrusted input.**

Everything interesting follows from that. `TestSuite.model_validate` is the
boundary, and it is the reason `generate_test_suite` can promise its caller a
well-formed object rather than a dict that might have anything in it. The retry
loop exists because a strict boundary means some answers get rejected, and one
rejection should not become a user-visible failure. The provider fallback exists
because free tiers rate limit without warning. The tests are split in two
because you cannot assert on exact text from something that answers differently
every time, but you can assert on properties that must hold for any valid
answer.

The alternative shape (parse loosely, hope for the best, discover the problem
when someone's `.feature` file will not parse three steps later) is easier to
write and much worse to use.

---

## 2. Every file, and why it exists

```
ai-testcase-generator/
├── app/
│   ├── generator.py         providers, retries, JSON parsing, serialisers
│   ├── models.py            the Pydantic models: TestSuite and friends
│   ├── prompts.py           versioned system prompts
│   └── streamlit_app.py     the local web UI
├── site/                    the browser demo, published to GitHub Pages
│   ├── index.html
│   ├── app.js               its own prompt copy and its own serialisers
│   ├── style.css
│   └── samples/login.json   a real answer, the no-backend fallback
├── tests/
│   ├── test_generator.py       22: 2 contract, 20 integration
│   └── test_browser_parity.py  4: the JS and Python copies must agree
├── examples/
│   ├── login_story.txt
│   └── checkout_story.txt
├── .github/workflows/
│   ├── tests.yml            pytest on push and pull request
│   └── pages.yml            publishes site/
├── requirements.txt         library and tests, no streamlit
├── requirements-ui.txt      the above, plus streamlit
└── .env.example
```

### `app/models.py`

Five Pydantic models, forty lines, and the most important file in the
repository. `GherkinStep` and `PytestStep` are the leaves; `GherkinScenario` and
`PytestTestCase` hold lists of them; `TestSuite` holds both lists plus a feature
name and the coverage notes.

It also carries this, which is worth explaining:

```python
class TestSuite(BaseModel):
    __test__ = False
```

Pytest collects anything named `Test*` that it finds in a test module's
namespace. `TestSuite` is imported into the test modules, so pytest tried to
collect it as a test class and printed a warning on every single run. Warnings
that fire every run stop being read, and then a real one arrives and nobody sees
it. `__test__ = False` is the flag pytest documents for exactly this.

### `app/generator.py`

The provider table, the retry loop, the JSON parsing, and the two serialisers.
Around 130 lines and the only file that knows a model exists.

### `app/prompts.py`

`SYSTEM_PROMPT_V1` and a version string. Nothing else in the Python codebase
knows what the prompt says, so changing prompt strategy touches one file.

### `app/streamlit_app.py`

The local UI. The first ten lines are a `sys.path` fix with a comment saying
why: `streamlit run app/streamlit_app.py` puts `app/` on the path but not the
project root, so `from app.generator import ...` would fail in the one run mode
the file exists to support.

### `site/`

The published demo. Covered in [section 9](#9-the-browser-demo-and-its-duplication),
because its duplication is a real design decision rather than an accident.

---

## 3. One call, end to end

```
   "As a registered user I want to log in..."
                  |
   available_providers(api_key)          which keys do we have?
                  |
   for provider in providers:            groq, then openrouter
     for attempt in 1..3:                a rejection is not a failure yet
                  |
       _client(provider, key)            an OpenAI client, different base_url
                  |
       chat.completions.create(...)      response_format json_object
                  |
       _strip_fences(content)            some models fence it anyway
                  |
       json.loads(...)                   ValueError if it is not JSON
                  |
       TestSuite.model_validate(...)     ValidationError if the shape is wrong
                  |
              TestSuite                  <- the only thing a caller ever sees
```

Every arrow after the model call can raise. If any of them does, the loop tries
again, and if every provider has run out of attempts, a `RuntimeError` names
each failure in order. The caller either gets a valid `TestSuite` or gets an
exception that says what went wrong; it never gets a half-parsed dict.

### Why three attempts

```python
ATTEMPTS_PER_PROVIDER = 3
```

The schema asks the model to put generated Python inside JSON strings. Nested
quoting is the thing models are worst at, so occasionally one emits a stray
brace and strict JSON mode rejects the whole response. Sampling again almost
always produces valid output, because it is a sampling artifact rather than a
misunderstanding of the prompt.

This is worth being precise about, because "just retry it" is usually a code
smell. Retrying is right here specifically because the failure is
non-deterministic and independent between attempts. If the prompt were wrong,
three attempts would fail three times and the error would say so.

### Why fences get stripped

```python
def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()
```

`response_format={"type": "json_object"}` is supposed to make this unnecessary.
Sometimes it does not, particularly on the fallback provider. Six lines here
prevent a whole class of failure that would otherwise look like "the model is
broken", and one of the two contract tests pins it.

---

## 4. The models, and why validation sits at the boundary

This is the argument the project is really making, so it is worth making it
properly.

Without validation, `generate_test_suite` returns a dict. The caller writes
`suite["scenarios"][0]["steps"]` and it works, until the day the model returns
`"scenario"` singular, or omits `steps` on one scenario out of six, or puts a
string where a list belongs. Then you get a `KeyError` in the serialiser, or
worse, a `.feature` file that is written successfully and fails to parse in
somebody's CI tomorrow.

With validation, `TestSuite.model_validate(data)` raises immediately, at the
point where the bad data entered the system, with a message naming the field.

```python
return TestSuite.model_validate(data)
```

One line, and everything downstream can stop defending itself. `suite_to_gherkin`
does not check whether `scenario.steps` exists, because it cannot not exist.

The general form: **validate untrusted input at the boundary, once, and let the
type system carry the guarantee from there.** A language model is untrusted
input. It is friendlier and better-behaved than a hostile HTTP client, and it is
in exactly the same category.

Two smaller decisions inside the models:

`tags: List[str] = Field(default_factory=list)` means a scenario with no tags is
valid. Tags are genuinely optional in Gherkin and rejecting an untagged scenario
would be stricter than the format.

`coverage_notes: str = Field(...)` is required. A model that will not say what
it left out has not really finished the job, and the field is the honest part of
the output.

---

## 5. The provider chain

```python
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
}
```

Groq is first because its free tier allows 1,000 requests a day against
OpenRouter's 50, and it supports a real JSON mode rather than requiring the JSON
to be scraped out of prose.

Both speak the OpenAI wire format, which is the only reason this table is as
small as it is. One `OpenAI` client class covers both, and the difference
between providers reduces to a base URL and a model slug.

The OpenRouter slug ends in `:free` deliberately, and the comment in the file
says why: a paid slug stops working the moment an account's balance reaches
zero, which is a failure that arrives without warning on a project nobody is
watching the billing for.

`available_providers(api_key)` has one asymmetry worth knowing about:

```python
def available_providers(api_key: str = None):
    """A supplied key is treated as a Groq key, which is what the UI passes through."""
    if api_key:
        return [("groq", api_key)]
```

A key passed in by a caller is assumed to be a Groq key, because the UIs that
pass one are asking the visitor for a Groq key specifically. If you want to pass
an OpenRouter key programmatically, set the environment variable rather than the
argument.

---

## 6. The serialisers

```python
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
```

Pure functions, no I/O, no model. Given a `TestSuite` they always produce the
same string, which is what makes them testable without a network and what makes
the JavaScript parity check possible at all.

They are also where the two output formats stay honest about their conventions:
two spaces before `Scenario`, four before a step, a blank line between
scenarios. Gherkin does not strictly require the indentation, but every tool
that renders it assumes it, and output that does not look like what people
expect gets distrusted.

---

## 7. The prompt

`SYSTEM_PROMPT_V1` does four things, and each of them was added because its
absence caused a specific problem.

**It gives the JSON schema inline.** Even with `response_format` set, the model
needs to be told what the fields are called.

**It asks for between three and seven scenarios, and says not to pad.** Without
a range you get either two scenarios or nineteen, and the nineteen are mostly
restatements of each other.

**It says scenario names must be specific.** The example in the prompt is
`"Successful login with valid credentials"` rather than `"Test login"`. Models
default to the generic version, and a list of generic names is much less useful
than it looks.

**It requires `coverage_notes` to name what was left out.** This is the clause
that makes the output trustworthy, because a list of scenarios with no statement
of scope reads as complete whether or not it is.

That last clause is also the one that went missing from the JavaScript copy for
a while. See the next section.

---

## 8. Three surfaces, one library

Everything routes through `generate_test_suite`. The surfaces differ only in how
they collect the story and what they do with the result.

| Surface | Where | Needs installing | Needs a key |
|---|---|---|---|
| Library | `from app.generator import ...` | Python and four packages | Yes, in `.env` |
| Streamlit app | `streamlit run app/streamlit_app.py` | The above plus streamlit | Yes, or paste one in |
| Browser demo | [the published page](https://priya123z.github.io/ai-testcase-generator/) | Nothing | No |

The browser demo is the only one that works with no key at all, and that is the
point of it: someone reading a CV should be able to click a link and see the
thing work, not read instructions about virtual environments.

`streamlit` living in `requirements-ui.txt` rather than `requirements.txt` is a
small decision with a clear rule behind it: **a dependency belongs in the file
for the surface that imports it.** Only `app/streamlit_app.py` imports
streamlit, so installing a web framework in order to run a test suite that never
touches one is a slow install for nothing, and CI installs the lighter file.

---

## 9. The browser demo, and its duplication

`site/app.js` carries its own copy of the system prompt and its own
implementations of `toGherkin` and `toPytest`. That is real duplication and it
is not an oversight: the page is static, served from GitHub Pages, with no
Python anywhere in the path. There is nothing for it to import.

The honest options were: accept the duplication and pin it with tests, or add a
build step that generates the JavaScript from the Python. The second is a
reasonable choice for a larger project. For three functions and a string, a
build step is more machinery than the problem deserves, and it puts a
transpilation between the source and the deployed artifact for a page whose main
virtue is that you can read the whole thing.

So the duplication is pinned instead, by `tests/test_browser_parity.py`:

```python
def test_prompt_matches_python():
    from app.prompts import SYSTEM_PROMPT_V1
    assert js_prompt() == SYSTEM_PROMPT_V1

@needs_node
def test_gherkin_matches_python(sample):
    assert run_js("toGherkin", sample) == suite_to_gherkin(TestSuite(**sample))
```

`run_js` reads `site/app.js`, slices out the two functions by their comment
markers, and runs them under `node -e` with no DOM. Which means the test runs
the actual shipped code rather than a copy of it.

**The prompt check is there because the drift already happened.** The two copies
had diverged: the JavaScript one had lost the clause requiring `coverage_notes`
to name what was left out, and had `3-7` where Python had a different dash. So
the same requirement produced measurably different output depending on whether a
visitor had pasted their own key. Nothing caught it, because nothing was
comparing them. Now something is, and it fails on a single changed character.

That is the general lesson worth taking from this file: **if you must duplicate,
make the duplication testable and then test it.** Duplication that is written
down and asserted on is a maintenance cost. Duplication that nothing checks is a
bug waiting for a quiet afternoon.

### How the demo answers

Three ways, tried in order, and the page always says which one it used:

1. **The visitor pasted a key.** The browser calls Groq directly. Groq allows
   cross-origin requests, so nothing of mine is in that path.
2. **Nobody pasted anything, and the Worker is up.** A Cloudflare Worker holds
   my Groq key as a secret and answers on it, inside a daily budget of 400 runs
   across everyone and 12 per visitor. It lives in the
   [portfolio repository](https://github.com/Priya123z/Priya123z.github.io/tree/main/worker)
   and serves that page too, since this one is a GitHub project page and
   therefore the same origin.
3. **Neither.** The saved answer in `site/samples/login.json`.

The key cannot go in the page, because the page is public and a key in
`app.js` is a key in devtools. That is the entire reason the Worker exists.

The third path is the guarantee rather than the consolation prize: whatever is
down, the demo cannot show a broken widget, and it cannot show a saved answer
dressed up as a live one either. `test_saved_answer_is_a_valid_suite` validates
that sample against the same Pydantic model, so the fallback cannot silently
drift out of the shape the page expects.

---

## 10. Testing something that answers differently every time

This is the part of the repository worth reading if you only read one.

The problem: two runs on the same requirement produce different scenarios,
different wording, different counts. Asserting on exact text gives you a suite
that fails constantly for no reason, and a suite that fails for no reason gets
muted, and a muted suite is worse than none.

The answer is to split the tests by what they can actually know.

### Contract tests: patch the network

Two of them, and they exist because you cannot reliably instruct a live model to
return deliberately broken output.

```python
def test_invalid_json_raises_value_error(self):
    bad = MagicMock()
    bad.choices = [MagicMock(message=MagicMock(content="not json at all {{"))]
    with patch("app.generator._client") as build:
        build.return_value.chat.completions.create.return_value = bad
        with pytest.raises(RuntimeError, match="invalid JSON"):
            generate_test_suite("test story", api_key="fake")
```

The patch is at `app.generator._client`, which is the transport boundary. That
matters: patching lower would test the OpenAI SDK, and patching higher would
test nothing. The other one feeds fenced JSON through and asserts it comes out
as a valid `TestSuite`, pinning `_strip_fences`.

These are the only mocks in the project, and they are here because the behaviour
under test is *how the code reacts to bad input*, which is not a property of the
model at all.

### Integration tests: call a real model, assert on properties

Twenty of them, sharing one API call through a module-scoped fixture, skipped
when no key is set.

```python
@pytest.fixture(scope="module")
def real_suite() -> TestSuite:
    if not HAS_KEY:
        pytest.skip("no API key set")
    return generate_test_suite(LOGIN_STORY)
```

They assert things that must be true of *any* sensible answer:

- every step keyword is one of Given, When, Then, And, But
- every pytest function name matches `test_[a-z0-9_]+`
- the scenario count is inside the range the prompt asked for
- rendered Gherkin starts with `Feature:` and rendered Python with `import pytest`
- every function name in the object appears in the rendered file

None of those depend on what the model chose to write. All of them fail if the
model starts returning something structurally wrong, which is the failure worth
catching.

### Why they skip rather than fail

```bash
pytest                        # no key:   6 passed, 20 skipped
GROQ_API_KEY=gsk_... pytest   # with key: 26 passed
```

A clean clone with no key runs the contract tests and passes. That is deliberate
and it is what keeps the build green on a fork, where a contributor has no
access to secrets. `-rs` prints the skip reasons, so skipped is never confused
with absent.

---

## 11. CI

`.github/workflows/tests.yml` runs pytest on push and on pull request, passing
both provider keys through from repository secrets:

```yaml
env:
  GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

Neither is required. Without them the integration tests skip and the contract
tests pass, which is exactly what happens on a fork and is the whole point of
the split.

The comment in the workflow says Groq's key specifically has to be present, not
just one of the two, because Groq is tried first and the skip condition checks
for either. It is the kind of thing that is obvious once and confusing a year
later.

`.github/workflows/pages.yml` publishes `site/` to GitHub Pages. Nothing is
built; the directory is served as it stands.

---

## 12. Running it yourself

```bash
git clone https://github.com/Priya123z/ai-testcase-generator.git
cd ai-testcase-generator

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest                       # 6 passed, 20 skipped, no key needed
```

For live output, get a free Groq key at
[console.groq.com/keys](https://console.groq.com/keys) (no card, about a
minute), then:

```bash
cp .env.example .env         # put the key in it
python -c "
from app.generator import generate_test_suite, suite_to_gherkin
print(suite_to_gherkin(generate_test_suite(open('examples/login_story.txt').read())))
"
```

For the UI:

```bash
pip install -r requirements-ui.txt
streamlit run app/streamlit_app.py
```

Overriding the model per call:

```python
suite = generate_test_suite(story, model="llama-3.3-70b-versatile")
```

### A sanity check by hand

Run the same story twice and diff the two outputs. They will differ, and that is
the point: it is why the integration tests assert on properties. If they come
back identical, something is caching that you did not expect.

Then read `coverage_notes` on both. If it is vague or empty, the prompt is not
doing its job and that is where to start iterating.

---

## 13. Decisions, and the ones worth arguing about

**Pydantic rather than a hand-rolled check.** The validation is declarative, the
error messages name the field and the path, and the models double as
documentation of the contract. A hand-rolled version would be forty lines of
`if isinstance` that nobody keeps current.

**The OpenAI SDK rather than raw HTTP.** Both providers speak that wire format,
so one client covers both and the provider table stays four lines each.

**Retries per provider, not per call.** Three attempts on Groq before falling
back to OpenRouter, rather than alternating. Groq is faster and has the larger
free tier, so exhausting it first is the right order.

**No caching.** Two runs on the same story are supposed to differ; caching would
hide the non-determinism that the design is built around acknowledging.

**Worth arguing about:** `ATTEMPTS_PER_PROVIDER = 3` with no backoff between
attempts. If the failure were a rate limit rather than a sampling artifact,
three immediate retries make it worse. The counter-argument is that a rate limit
raises a distinguishable error and the fallback provider handles it, but a
short sleep between attempts would cost nothing and I would probably add it.

**Also worth arguing about:** the fenced-JSON stripping papers over a provider
not honouring `response_format`. Some would say let it fail loudly and pick a
provider that behaves. I would rather the six lines than the support burden.

---

## 14. What it does not do

**It does not know your domain.** It has never seen your billing rules. Given a
story about proration it will write a confident, plausible, wrong scenario. This
is the single most important limitation and the reason `coverage_notes` is a
required field.

**It does not produce runnable tests.** The pytest output is skeletons: function
names, docstrings, and commented steps. Filling in the bodies is the work, and
the tool is explicitly a starting point for it.

**There is no prompt evaluation harness.** `SYSTEM_PROMPT_V1` is versioned, but
nothing measures whether V2 is better than V1. A proper setup would run a set of
stories through both and score the results, and that is the most interesting
thing this project is missing.

**No streaming.** The Streamlit app blocks for the several seconds a generation
takes. Streaming would make it feel faster and is not implemented.

**No cost accounting.** Free tiers only. Point it at a paid model and nothing
tracks what you are spending.

---

## 15. FAQ

**Why validate the model's output at all? It is JSON mode.**
JSON mode guarantees you get JSON. It does not guarantee the JSON has your
fields, in your types, with your required keys present. Those are different
promises, and only the second one lets a serialiser stop defending itself.

**Why not just retry forever until it parses?**
Because a prompt that is genuinely wrong would then hang instead of failing.
Three attempts is enough for a sampling artifact and short enough that a real
problem surfaces as an error naming every attempt.

**Why two providers?**
Free tiers rate limit without warning and usually at the least convenient
moment. The second is not for redundancy in the datacentre sense; it is so a
demo linked from a CV does not go dark because someone else was busy.

**Why is the browser demo not just an iframe of the Streamlit app?**
Streamlit needs a server, and free hosting for one either sleeps after fifteen
minutes or costs money. A static page has neither problem, and the Worker gives
it live answers for the cost of a Cloudflare account.

**Is duplicating the prompt in JavaScript not just bad?**
It is a cost. The alternatives are a build step or a server, and for three
functions and a string both are more machinery than the problem deserves. What
makes it acceptable is that a test fails the moment the copies diverge, which is
more than most duplication gets.

**Why do the integration tests share one API call?**
Twenty calls for twenty assertions about the same answer would be twenty times
slower, twenty times the quota, and would test the model's consistency rather
than the code. The module-scoped fixture makes them twenty assertions about one
answer, which is what they are actually for.

**Why does `pytest` pass on a clone with no key?**
So it does. The contract tests cover the logic that does not need a model, and a
build that goes red on a fork because a secret is missing teaches contributors
to ignore red builds.

**Can I use a different model?**
`generate_test_suite(story, model="...")` overrides the slug for one call. Any
model with a working JSON mode should work; ones without will lean on
`_strip_fences` and fail more often.

**What happens if the model returns valid JSON with nonsense content?**
It comes back. Validation checks structure, not truth: a scenario named
"Scenario 1" with steps that make no sense is structurally perfect. That is what
human review is for, and it is why the README is explicit that this is a
starting point rather than a replacement.

**Why is `__test__ = False` on `TestSuite`?**
Because pytest collects anything named `Test*` in a test module's namespace and
warned about it on every run. Warnings that fire every run stop being read, and
then a real one arrives and nobody sees it.
