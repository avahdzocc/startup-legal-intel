"""
Startup Legal Intelligence Agent
A natural language interface for querying SEC filing data.

Usage:
    streamlit run app.py
"""

import streamlit as st
import sys
from pathlib import Path

# Add scripts directory to path so we can import the translator
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from ai_translator_module import query


def escape_dollars(text):
    """Escape $ signs so Streamlit doesn't interpret them as LaTeX."""
    return text.replace("$", "\\$")


# --- Page config ---
st.set_page_config(
    page_title="Startup Legal Intelligence Agent",
    page_icon="§",
    layout="wide",
)

# --- Custom styling ---
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .sql-box {
        background-color: #f8f9fa;
        border: 1px solid #e1e4e8;
        border-radius: 6px;
        padding: 12px;
        font-family: 'SF Mono', 'Fira Code', monospace;
        font-size: 0.85rem;
        white-space: pre-wrap;
        margin: 0.5rem 0;
    }
    .stChatMessage {
        padding: 1rem;
    }
    /* Override red focus border on chat input */
    .stChatInput textarea:focus,
    .stChatInput textarea:focus-visible,
    .stChatInput div:focus-within {
        border-color: #4a90d9 !important;
        box-shadow: 0 0 0 1px #4a90d9 !important;
        outline: none !important;
    }
    .stChatInput textarea {
        border-color: #d1d5db !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown('<div class="main-header">§ Startup Legal Intelligence Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    'Query SEC Form D and S-1 filing data using natural language. '
    'Powered by Claude + DuckDB.'
    '</div>',
    unsafe_allow_html=True,
)

# --- Sidebar ---
with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "This tool queries a local database of **603K+ Form D filings** "
        "and **68K S-1 registrations** from the SEC, spanning 2009–2025."
    )

    st.markdown("### Example Questions")
    examples = [
        "Which states have the highest IPO rates?",
        "How many biotech companies filed Form D offerings?",
        "What industries raise the most capital?",
        "Show me the top venture capital fund states",
        "What is the average offering size for pharma companies?",
        "Which entity types are most likely to IPO?",
        "Compare IPO rates: California vs New York vs Texas",
    ]
    for ex in examples:
        if st.button(ex, key=ex, use_container_width=True):
            st.session_state["pending_question"] = ex

    st.markdown("---")
    st.markdown(
        "### Data Sources\n"
        "- [SEC Form D Data Sets](https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets)\n"
        "- [EDGAR Full Index](https://www.sec.gov/Archives/edgar/full-index/)"
    )

# --- Chat state ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Display chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(escape_dollars(msg["content"]))
        if "sql" in msg:
            with st.expander("View SQL Query"):
                st.code(msg["sql"], language="sql")
        if "data" in msg:
            with st.expander(f"View Raw Data ({msg['row_count']} rows)"):
                st.dataframe(msg["data"])

# --- Handle input ---
# Check for sidebar button click or chat input
prompt = None
if "pending_question" in st.session_state:
    prompt = st.session_state.pop("pending_question")

chat_input = st.chat_input("Ask a question about SEC filing data...")
if chat_input:
    prompt = chat_input

if prompt:
    # Display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build conversation history for follow-up context
    history = []
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            history.append({"question": msg["content"]})
        elif msg["role"] == "assistant" and "sql" in msg and history:
            history[-1]["sql"] = msg["sql"]
    conv_history = [(h["question"], h["sql"]) for h in history if "sql" in h]

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing SEC data..."):
            result = query(prompt, history=conv_history)

        if result["error"]:
            error_msg = f"Something went wrong: {result['error']}"
            if result["sql"]:
                error_msg += f"\n\nGenerated SQL:\n```sql\n{result['sql']}\n```"
            st.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg,
            })
        else:
            # Show the summary
            st.markdown(escape_dollars(result["summary"]))

            # Show SQL in expander
            with st.expander("View SQL Query"):
                st.code(result["sql"], language="sql")

            # Show raw data in expander
            if result["rows"]:
                import pandas as pd
                df = pd.DataFrame(result["rows"], columns=result["columns"])
                with st.expander(f"View Raw Data ({len(result['rows'])} rows)"):
                    st.dataframe(df, use_container_width=True)

            # Save to chat history
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["summary"],
                "sql": result["sql"],
                "data": result["rows"],
                "row_count": len(result["rows"]),
            })
