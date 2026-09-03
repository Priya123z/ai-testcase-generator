/* The demo on this page.

   It talks to Groq straight from the browser using whatever key the visitor
   pastes in. Groq answers preflight with access-control-allow-origin: *, so no
   server is involved — nothing is proxied, nothing is stored, and the key is
   gone when the tab closes. With no key you get a saved answer from a real run,
   labelled as saved.

   SYSTEM_PROMPT and the two serialisers below mirror app/prompts.py and
   app/generator.py. That is real duplication: this page has no Python to call.
   If you change one, change the other. */

const MODEL = "openai/gpt-oss-120b";
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";

const SYSTEM_PROMPT = `You are a senior QA engineer. Your job is to analyse a user story and generate comprehensive, well-structured test cases.

For every user story you receive, you must produce:
1. A set of Gherkin scenarios (BDD format) covering:
   - The happy path
   - Key negative paths (invalid input, boundary conditions)
   - Edge cases where the domain demands them
2. A matching set of Pytest test function skeletons (one per scenario)
3. A brief coverage note

RULES:
- Generate 3-7 scenarios per story. Do not pad. Do not truncate real cases.
- Scenario names must be specific, not generic ("Successful login with valid credentials" not "Test login").
- Gherkin steps must be concrete - use real-looking data values in Given/When steps.
- Pytest function names must be snake_case starting with test_.
- The coverage_notes field must honestly note what edge cases you are NOT generating.
- You MUST return valid JSON matching the schema below. No markdown fences, no prose before or after.

JSON SCHEMA:
{
  "feature": "string",
  "scenarios": [
    {"name": "string", "tags": ["string"],
     "steps": [{"keyword": "Given|When|Then|And", "text": "string"}]}
  ],
  "pytest_cases": [
    {"function_name": "string", "docstring": "string",
     "steps": [{"description": "string", "code": "string"}]}
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
    throw new Error("Groq rejected that key. Check it at console.groq.com/keys, or clear the field to see the saved answer.");
  }
  if (resp.status === 429) {
    throw new Error("That key hit its rate limit. Wait a minute — the free tier allows 30 requests per minute.");
  }
  if (!resp.ok) throw new Error(data?.error?.message || `Groq answered ${resp.status}.`);

  return JSON.parse(data.choices[0].message.content);
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

function render(suite, source) {
  current = suite;
  const n = suite.scenarios.length;
  const c = (suite.pytest_cases || []).length;

  $("stamp").className = "stamp " + (source === "live" ? "stamp-live" : "stamp-saved");
  $("stamp").textContent = source === "live"
    ? `Live — ${n} scenarios and ${c} Pytest cases, generated just now by ${MODEL} on your key.`
    : `Saved answer from a real run, not generated just now. Add a free Groq key below and the same story runs live in your browser.`;

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
  btn.textContent = key ? "Asking the model…" : "Loading…";

  try {
    if (key) {
      render(validate(await callGroq(story, key)), "live");
    } else {
      const resp = await fetch("samples/login.json");
      if (!resp.ok) throw new Error("Could not load the saved answer. Try reloading the page.");
      render(validate(await resp.json()), "saved");
    }
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

$("key").addEventListener("input", () => {
  $("mode").textContent = $("key").value.trim()
    ? "your key — answers live"
    : "saved answer — add a key to run live";
});

$("year").textContent = new Date().getFullYear();
