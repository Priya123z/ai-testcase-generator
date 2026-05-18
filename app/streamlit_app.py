import streamlit as st
import openai
from dotenv import load_dotenv
from app.generator import generate_test_suite, suite_to_gherkin, suite_to_pytest
from app.models import TestSuite

load_dotenv()

st.set_page_config(
    page_title="AI Test-Case Generator",
    page_icon="🧪",
    layout="wide",
)

st.title("🧪 AI Test-Case Generator")
st.caption("Convert plain-text user stories into Gherkin scenarios + Pytest skeletons — powered by OpenRouter AI.")

with st.expander("ℹ️ How to use", expanded=False):
    st.markdown("""
1. Paste a user story (one or more sentences describing a feature and its acceptance criteria).
2. Click **Generate**.
3. Review the output — Gherkin tab for BDD, Pytest tab for code, JSON tab for the raw structured data.
4. Download the files you need.

**Note:** Generated tests are starting points for QA review, not a replacement for human test design.
The generator works best with stories that include clear acceptance criteria.
""")

st.subheader("User Story")
example = """As a registered user, I want to log in with my email and password so that I can access my dashboard.

Acceptance criteria:
- Valid credentials redirect to /dashboard
- Account locks after 3 consecutive failed attempts
- Empty email or password shows inline validation error
- "Remember me" checkbox keeps the session for 30 days"""

story_input = st.text_area(
    "Paste your user story here",
    value=example,
    height=160,
    help="Include acceptance criteria for better coverage",
)

col1, col2 = st.columns([1, 4])
with col1:
    generate_btn = st.button("🚀 Generate", type="primary", use_container_width=True)

if generate_btn:
    if not story_input.strip():
        st.error("Please enter a user story before generating.")
    else:
        with st.spinner("Generating test cases with AI..."):
            try:
                suite: TestSuite = generate_test_suite(story_input)
                gherkin_output = suite_to_gherkin(suite)
                pytest_output = suite_to_pytest(suite)

                st.success(f"✅ Generated {len(suite.scenarios)} scenarios across {len(suite.pytest_cases)} test cases")

                tab1, tab2, tab3 = st.tabs(["🥒 Gherkin (.feature)", "🐍 Pytest (.py)", "📦 JSON"])

                with tab1:
                    st.code(gherkin_output, language="gherkin")
                    st.download_button(
                        "⬇️ Download .feature",
                        gherkin_output,
                        file_name=f"{suite.feature.lower().replace(' ', '_')}.feature",
                        mime="text/plain",
                    )

                with tab2:
                    st.code(pytest_output, language="python")
                    st.download_button(
                        "⬇️ Download .py",
                        pytest_output,
                        file_name=f"test_{suite.feature.lower().replace(' ', '_')}.py",
                        mime="text/plain",
                    )

                with tab3:
                    st.json(suite.model_dump())

                if suite.coverage_notes:
                    st.info(f"**Coverage note:** {suite.coverage_notes}")

            except openai.AuthenticationError:
                st.error("❌ Authentication failed. Please set a valid OPENROUTER_API_KEY in your .env file.")
            except openai.APIConnectionError:
                st.error("❌ Could not connect to OpenRouter. Check your internet connection.")
            except ValueError as e:
                st.error(f"❌ Failed to parse LLM output: {e}")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")
