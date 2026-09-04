/* The demo on this page.

   Three ways an answer can arrive, tried in this order, and the page always says
   which one it used:

     1. The visitor pasted their own Groq key, and the browser calls Groq
        directly. Groq answers preflight with access-control-allow-origin: *, so
        no server is involved, nothing is proxied, nothing is stored, and the key
        is gone when the tab closes.
     2. Nobody pasted anything, and the Worker is deployed. It holds a Groq key
        as a Cloudflare secret and answers on it inside a daily budget, which is
        what lets this page work without asking anyone to go and sign up first.
        It lives in the portfolio repository under worker/ and serves that page
        too; this one is a project page, so it is the same origin.
     3. Neither. The saved answer in samples/, labelled as saved.

   SYSTEM_PROMPT and the two serialisers below mirror app/prompts.py and
   app/generator.py. That is real duplication, because this page has no Python to
   call. tests/test_browser_parity.py fails if either copy drifts. */

const MODEL = "openai/gpt-oss-120b";
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const API_BASE = (document.body.dataset.api || "").replace(/\/+$/, "");

/* Set by probe() shortly after load. Until it answers the page assumes there is
   no backend, which is the safe way round: better to say "saved answer" and be
   pleasantly wrong than to promise a live one and not have it. */
let backend = false;

const SYSTEM_PROMPT = `You are a senior QA engineer. Your job is to analyse a user story and generate comprehensive, well-structured test cases.

For every user story you receive, you must produce:
1. A set of Gherkin scenarios (BDD format) covering:
   - The happy path
   - Key negative paths (invalid input, boundary conditions)
   - Edge cases where the domain demands them
2. A matching set of Pytest test function skeletons (one per scenario)
3. A brief coverage note

RULES:
- Generate 3 to 7 scenarios per story. Do not pad. Do not truncate real cases.
- Scenario names must be specific, not generic ("Successful login with valid credentials" not "Test login").
- Gherkin steps must be concrete: use real-looking data values in Given/When steps.
- Pytest function names must be snake_case starting with test_.
- The coverage_notes field must honestly note what edge cases you are NOT generating (e.g. "Session management and MFA flows are out of scope for this story").
- You MUST return valid JSON matching the schema below. No markdown fences, no prose before or after.

JSON SCHEMA:
{
  "feature": "string",
  "scenarios": [
    {
      "name": "string",
      "tags": ["string"],
      "steps": [
        { "keyword": "Given|When|Then|And", "text": "string" }
      ]
    }
  ],
  "pytest_cases": [
    {
      "function_name": "string",
      "docstring": "string",
      "steps": [
        { "description": "string", "code": "string" }
      ]
    }
  ],
  "coverage_notes": "string"
}`;

// Mirrors suite_to_gherkin in app/generator.py
function toGherkin(s) {
  const lines = [`Feature: ${s.feature}`, ""];
  for (const sc of s.scenarios || []) {
    if (sc.tags?.length) lines.push("  " + sc.tags.map(t => `@${t}`).join(" "));
    lines.push(`  Scenario: ${sc.name}`);
    for (const st of sc.steps || []) lines.push(`    ${st.keyword} ${st.text}`);
    lines.push("");
  }
  return lines.join("\n");
}

// Mirrors suite_to_pytest in app/generator.py
function toPytest(s) {
  const lines = ["import pytest", "", ""];
  for (const tc of s.pytest_cases || []) {
    lines.push(`def ${tc.function_name}():`);
    lines.push(`    """${tc.docstring}"""`);
    for (const st of tc.steps || []) {
      lines.push(`    # ${st.description}`);
      lines.push(`    ${st.code}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

const $ = id => document.getElementById(id);
let current = null;

async function callGroq(story, key) {
  const resp = await fetch(GROQ_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model: MODEL,
      temperature: 0.2,
      max_tokens: 8000,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: story },
      ],
    }),
  });

  const data = await resp.json().catch(() => ({}));

  if (resp.status === 401) {
    throw new Error("Groq rejected that key. Check it at console.groq.com/keys, or clear the field and this runs on the shared key instead.");
  }
  if (resp.status === 429) {
    throw new Error("That key has hit its rate limit. The free tier allows 30 requests a minute, so give it about a minute.");
  }
  if (!resp.ok) throw new Error(data?.error?.message || `Groq answered ${resp.status}.`);

  return JSON.parse(data.choices[0].message.content);
}

async function callBackend(story) {
  const resp = await fetch(`${API_BASE}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ story }),
  });
  if (!resp.ok) throw new Error(`the backend answered ${resp.status}`);

  const data = await resp.json();
  return { suite: data.result, meta: data.meta || {} };
}

async function savedAnswer() {
  const resp = await fetch("samples/login.json");
  if (!resp.ok) throw new Error("Could not load the saved answer. Try reloading the page.");
  return { suite: await resp.json(), meta: { source: "saved" } };
}

/* One call at load so the line under the button is telling the truth before
   anyone presses it. Never awaited by anything: if it does not come back, the
   page stays on saved answers and stays usable. */
async function probe() {
  if (!API_BASE) return;
  try {
    const resp = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(4000) });
    if (!resp.ok) return;
    backend = Boolean((await resp.json()).shared_key);
  } catch {
    /* Worker asleep, offline, or never deployed. */
  } finally {
    showMode();
  }
}

// The same validation the Python side does through Pydantic. A model that
// returns almost-right JSON should fail here, not three files later.
function validate(s) {
  if (!s || typeof s.feature !== "string" || !s.feature.trim()) {
    throw new Error("The model did not return a feature name.");
  }
  if (!Array.isArray(s.scenarios) || !s.scenarios.length) {
    throw new Error("The model returned no scenarios.");
  }
  const allowed = ["Given", "When", "Then", "And", "But"];
  for (const sc of s.scenarios) {
    if (!sc.name || !Array.isArray(sc.steps) || !sc.steps.length) {
      throw new Error(`Scenario "${sc.name || "(unnamed)"}" has no steps.`);
    }
    for (const st of sc.steps) {
      if (!allowed.includes(st.keyword)) {
        throw new Error(`"${st.keyword}" is not a Gherkin keyword.`);
      }
    }
  }
  for (const tc of s.pytest_cases || []) {
    if (!/^test_[a-z0-9_]*$/.test(tc.function_name || "")) {
      throw new Error(`"${tc.function_name}" is not a snake_case test name.`);
    }
  }
  return s;
}

/* The line above every answer saying where it came from. Nothing here is
   decorative: a saved answer that is not marked as saved is a lie about what
   this page can do. */
function stampText(meta, n, c) {
  if (meta.source === "live") {
    const whose = meta.key === "byok" ? "your key" : "my key";
    return `Live: ${n} scenarios and ${c} Pytest cases, generated just now by ${MODEL} on ${whose}.`;
  }
  if (meta.source === "cached") {
    return `${whyCached(meta.reason)} Add your own key below and it runs live straight away.`;
  }
  return "A saved answer from a real earlier run, not generated just now. "
    + "Add a free Groq key below and the same story runs live in your browser.";
}

function whyCached(reason) {
  if (reason === "too_fast") return "A saved answer. That was a lot of requests in a minute, so the shared key is pausing you.";
  if (reason === "visitor_daily") return "A saved answer. You have used today's dozen free runs on my key.";
  if (reason === "daily_budget") return "A saved answer. Today's shared budget is spent; it resets at midnight UTC.";
  if (reason === "provider_busy") return "A saved answer. Groq is rate limiting the shared key at the moment.";
  if (reason === "provider_error") return "A saved answer. The model call failed, so this is the last known good one.";
  return "A saved answer from a real earlier run.";
}

function render(suite, meta) {
  current = suite;
  const n = suite.scenarios.length;
  const c = (suite.pytest_cases || []).length;

  $("stamp").className = "stamp " + (meta.source === "live" ? "stamp-live" : "stamp-saved");
  $("stamp").textContent = stampText(meta, n, c);

  $("feature").textContent = suite.feature;
  $("countline").textContent = `${n} scenario${n === 1 ? "" : "s"} · ${c} Pytest case${c === 1 ? "" : "s"}`;
  $("gherkin").textContent = toGherkin(suite);
  $("pytest").textContent = toPytest(suite);
  $("json").textContent = JSON.stringify(suite, null, 2);
  $("notes").textContent = suite.coverage_notes || "";
  $("notes-wrap").hidden = !suite.coverage_notes;
  $("result").hidden = false;
}

async function run() {
  const story = $("story").value.trim();
  const key = $("key").value.trim();
  const btn = $("run");
  const err = $("error");

  err.hidden = true;
  if (!story) {
    err.textContent = "Put a requirement in the box first.";
    err.hidden = false;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Asking the model…";

  try {
    let answer;

    if (key) {
      answer = { suite: await callGroq(story, key), meta: { source: "live", key: "byok" } };
    } else if (backend) {
      /* A backend that was up at load and is down now should still leave the
         visitor with something to read. */
      answer = await callBackend(story).catch(() => savedAnswer());
    } else {
      answer = await savedAnswer();
    }

    render(validate(answer.suite), answer.meta);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    $("result").hidden = true;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate test cases";
  }
}

function download(kind) {
  if (!current) return;
  const [text, name, type] = kind === "feature"
    ? [toGherkin(current), slug(current.feature) + ".feature", "text/plain"]
    : kind === "py"
    ? [toPytest(current), "test_" + slug(current.feature).replace(/-/g, "_") + ".py", "text/x-python"]
    : [JSON.stringify(current, null, 2), slug(current.feature) + ".json", "application/json"];

  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "suite";
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => {
      const on = t === tab;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", on);
    });
    document.querySelectorAll(".pane").forEach(p => {
      p.hidden = p.dataset.pane !== tab.dataset.pane;
    });
  });
});

$("run").addEventListener("click", run);
document.querySelectorAll("[data-dl]").forEach(b =>
  b.addEventListener("click", () => download(b.dataset.dl)));

function showMode() {
  const el = $("mode");
  if ($("key").value.trim()) el.textContent = "your key, answers live";
  else if (backend) el.textContent = "shared key, answers live";
  else el.textContent = "saved answer, add a key to run live";
}

$("key").addEventListener("input", showMode);
showMode();
probe();

$("year").textContent = new Date().getFullYear();
