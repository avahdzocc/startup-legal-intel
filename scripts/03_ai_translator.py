"""
Phase 3: Natural language to SQL translator using Claude API.

This module translates plain-English questions about SEC data into SQL,
executes them against the local DuckDB database, and returns a natural
language summary of the results.

Two-step process:
  1. Claude generates a DuckDB-compatible SQL query from the user's question
  2. The query runs against the local database
  3. Claude summarizes the results in plain English

Usage (standalone test):
    export ANTHROPIC_API_KEY="your-key-here"
    python3 scripts/03_ai_translator.py
"""

import anthropic
import duckdb
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "db" / "sec_data.duckdb"

# Auto-load API key from .env file if not already in environment
env_file = PROJECT_DIR / ".env"
if env_file.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
    for line in env_file.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()

MODEL = "claude-sonnet-4-6"

# --- Schema context for Claude ---
# This tells Claude exactly what tables/columns exist and what the data looks like.
SCHEMA_PROMPT = """You are a SQL query generator for a DuckDB database containing SEC filing data.
The database tracks private securities offerings (Form D filings) and IPO registrations (S-1 filings).

## Tables

### FormDIssuers (603,124 rows) — One row per issuer per filing
- ACCESSIONNUMBER (VARCHAR): Unique SEC submission ID, e.g. '0001567619-19-018882'
- IS_PRIMARYISSUER_FLAG (VARCHAR): 'YES' or 'NO'
- ISSUER_SEQ_KEY (VARCHAR): Sequence key within a filing
- CIK (VARCHAR): Central Index Key, zero-padded to 10 digits, e.g. '0001781755'
- ENTITYNAME (VARCHAR): Company name
- STREET1, STREET2 (VARCHAR): Address lines
- CITY (VARCHAR): City name
- STATEORCOUNTRY (VARCHAR): 2-letter code for US states (CA, NY, TX), alphanumeric for foreign
- STATEORCOUNTRYDESCRIPTION (VARCHAR): Full name, e.g. 'CALIFORNIA'
- ZIPCODE (VARCHAR): Postal code
- ISSUERPHONENUMBER (VARCHAR): Phone number
- JURISDICTIONOFINC (VARCHAR): Where incorporated, e.g. 'DELAWARE', 'CAYMAN ISLANDS'
- ISSUER_PREVIOUSNAME_1, _2, _3 (VARCHAR): Previous company names
- EDGAR_PREVIOUSNAME_1, _2, _3 (VARCHAR): Previous names in EDGAR system
- ENTITYTYPE (VARCHAR): e.g. 'Corporation', 'Limited Liability Company', 'Limited Partnership'
- ENTITYTYPEOTHERDESC (VARCHAR): Description if EntityType is 'Other'
- YEAROFINC_TIMESPAN_CHOICE (VARCHAR): 'overFiveYears', 'withinFiveYears', 'yetToBeFormed'
- YEAROFINC_VALUE_ENTERED (VARCHAR): Year of incorporation, e.g. '2019'

### FormDOffering (593,847 rows) — One row per Form D filing
- ACCESSIONNUMBER (VARCHAR): Unique SEC submission ID (joins to FormDIssuers)
- INDUSTRYGROUPTYPE (VARCHAR): Industry category, e.g. 'Biotechnology', 'Pharmaceuticals', 'Other Technology', 'Pooled Investment Fund'
- INVESTMENTFUNDTYPE (VARCHAR): 'Hedge Fund', 'Venture Capital Fund', 'Private Equity Fund', 'Other Investment Fund', or NULL
- IS40ACT (VARCHAR): 'true'/'false' — Investment Company Act status
- REVENUERANGE (VARCHAR): e.g. 'No Revenues', '$1,000,001 - $5,000,000', 'Decline to Disclose'
- AGGREGATENETASSETVALUERANGE (VARCHAR): Net asset range for funds
- FEDERALEXEMPTIONS_ITEMS_LIST (VARCHAR): SEC exemption rules used
- ISAMENDMENT (VARCHAR): 'true'/'false' — whether this filing amends a prior one
- PREVIOUSACCESSIONNUMBER (VARCHAR): Prior filing if amendment
- SALE_DATE (VARCHAR): Date of first sale, e.g. '2011-02-01'
- YETTOOCCUR (VARCHAR): 'true' if sale hasn't happened yet
- MORETHANONEYEAR (VARCHAR): 'true'/'false'
- ISEQUITYTYPE, ISDEBTTYPE, ISOPTIONTOACQUIRETYPE, ISSECURITYTOBEACQUIREDTYPE, ISPOOLEDINVESTMENTFUNDTYPE, ISTENANTINCOMMONTYPE, ISMINERALPROPERTYTYPE, ISOTHERTYPE (VARCHAR): Security type flags ('true' or NULL)
- ISBUSINESSCOMBINATIONTRANS (VARCHAR): 'true'/'false'
- MINIMUMINVESTMENTACCEPTED (VARCHAR): Dollar amount as string
- TOTALOFFERINGAMOUNT (VARCHAR): Total intended raise as string
- TOTALAMOUNTSOLD (VARCHAR): Amount already sold as string
- TOTALREMAINING (VARCHAR): Amount remaining as string
- HASNONACCREDITEDINVESTORS (VARCHAR): 'true'/'false'
- NUMBERNONACCREDITEDINVESTORS (VARCHAR): Count as string
- TOTALNUMBERALREADYINVESTED (VARCHAR): Investor count as string

### FormDSubmission (593,847 rows) — Filing metadata
- ACCESSIONNUMBER (VARCHAR): Unique SEC submission ID
- FILE_NUM (VARCHAR): SEC file number
- FILING_DATE (VARCHAR): Date filed, format varies: '14-DEC-2021' or similar
- SIC_CODE (VARCHAR): Standard Industrial Classification code
- SUBMISSIONTYPE (VARCHAR): 'D' (original) or 'D/A' (amendment)
- TESTORLIVE (VARCHAR): Always 'LIVE' in production data

### S1Filings (68,183 rows) — IPO registration filings from EDGAR
- CIK (VARCHAR): Central Index Key, NOT zero-padded, e.g. '1001316'
- CompanyName (VARCHAR): Company name at time of S-1 filing
- FormType (VARCHAR): 'S-1', 'S-1/A', 'F-1', 'F-1/A'
- DateFiled (VARCHAR): Filing date, e.g. '2009-03-11'
- Filename (VARCHAR): EDGAR file path
- SourceQuarter (VARCHAR): e.g. '2009Q2', '2018Q1'

## Critical Join Logic
CIK links companies across tables. FormDIssuers.CIK is zero-padded to 10 digits.
S1Filings.CIK is NOT padded. To join them:
  FormDIssuers.CIK = RIGHT('0000000000' || S1Filings.CIK, 10)

FormDIssuers joins to FormDOffering and FormDSubmission via ACCESSIONNUMBER.

## Domain Knowledge
- Form D: Filed when a company makes a private, SEC-exempt securities offering
- S-1/F-1: Registration statement filed in anticipation of an IPO
- A company appearing in S1Filings indicates it pursued an IPO
- CIK: Central Index Key — SEC's unique company identifier
- To analyze original filings only (not amendments): filter WHERE ISAMENDMENT = 'false'
- US states use 2-letter codes (CA, NY); filter with regexp_matches(STATEORCOUNTRY, '^[A-Z]{2}$')
- Numeric fields (TOTALOFFERINGAMOUNT, etc.) are stored as VARCHAR — cast to DOUBLE when needed
- Use NULLIF and TRY_CAST for safe numeric conversion: TRY_CAST(TOTALOFFERINGAMOUNT AS DOUBLE)

## Rules
- Generate ONLY SELECT statements. Never generate INSERT, UPDATE, DELETE, DROP, or ALTER.
- Use DuckDB SQL syntax (|| for concat, DOUBLE not FLOAT, regexp_matches for regex).
- Always LIMIT results to 50 rows unless the user asks for more.
- When counting distinct companies, use DISTINCT CIK to avoid double-counting.
- Return ONLY the SQL query, no explanation or markdown formatting."""


def generate_sql(client, question):
    """Ask Claude to translate a natural language question into SQL."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SCHEMA_PROMPT,
        messages=[
            {"role": "user", "content": question}
        ]
    )
    sql = response.content[0].text.strip()
    # Strip markdown code fences if Claude includes them despite instructions
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1]
    if sql.endswith("```"):
        sql = sql.rsplit("```", 1)[0]
    return sql.strip()


def execute_sql(sql):
    """Run a SQL query against the local DuckDB database (read-only)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        result = con.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return columns, rows
    finally:
        con.close()


def summarize_results(client, question, sql, columns, rows):
    """Ask Claude to summarize query results in plain English."""
    if not rows:
        return "The query returned no results."

    # Format results as a readable table for Claude
    result_text = " | ".join(columns) + "\n"
    for row in rows[:50]:
        result_text += " | ".join(str(v) for v in row) + "\n"

    if len(rows) > 50:
        result_text += f"\n... ({len(rows)} total rows, showing first 50)"

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system="""You are a legal analytics assistant helping startup lawyers understand SEC data.
Summarize the query results concisely and clearly. Highlight the key takeaways.
Use plain language a lawyer would understand — not database jargon.
Format numbers nicely (percentages to 1 decimal, large numbers with commas).
Keep your response to 2-4 sentences for simple results, up to a short paragraph for complex ones.""",
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\n\nSQL executed:\n{sql}\n\nResults:\n{result_text}"
            }
        ]
    )
    return response.content[0].text


def query(question):
    """
    Main entry point: takes a natural language question, returns a dict with:
      - sql: the generated SQL query
      - columns: list of column names
      - rows: list of result tuples
      - summary: plain English summary
      - error: error message if something went wrong (None on success)
    """
    client = anthropic.Anthropic()

    # Step 1: Generate SQL
    try:
        sql = generate_sql(client, question)
    except Exception as e:
        return {"sql": None, "columns": [], "rows": [], "summary": None,
                "error": f"Failed to generate SQL: {e}"}

    # Step 2: Execute (with basic safety check)
    sql_upper = sql.upper().strip()
    if any(sql_upper.startswith(kw) for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]):
        return {"sql": sql, "columns": [], "rows": [], "summary": None,
                "error": "Safety check: only SELECT queries are allowed."}

    try:
        columns, rows = execute_sql(sql)
    except Exception as e:
        return {"sql": sql, "columns": [], "rows": [], "summary": None,
                "error": f"SQL execution error: {e}"}

    # Step 3: Summarize
    try:
        summary = summarize_results(client, question, sql, columns, rows)
    except Exception as e:
        summary = f"(Could not generate summary: {e})"

    return {"sql": sql, "columns": columns, "rows": rows, "summary": summary,
            "error": None}


# --- Standalone test ---
if __name__ == "__main__":
    test_questions = [
        "Which 5 states have the highest IPO rates?",
        "How many biotech companies filed Form D offerings?",
        "What are the top 10 industries by total amount of capital raised?",
    ]

    print("=" * 70)
    print("AI TRANSLATOR TEST")
    print("=" * 70)

    for q in test_questions:
        print(f"\nQuestion: {q}")
        print("-" * 70)
        result = query(q)

        if result["error"]:
            print(f"ERROR: {result['error']}")
            if result["sql"]:
                print(f"Generated SQL: {result['sql']}")
            continue

        print(f"SQL: {result['sql']}\n")
        print(f"Results: {len(result['rows'])} rows")
        if result["rows"]:
            print(f"Columns: {result['columns']}")
            for row in result["rows"][:5]:
                print(f"  {row}")
            if len(result["rows"]) > 5:
                print(f"  ... ({len(result['rows'])} total)")
        print(f"\nSummary: {result['summary']}")
        print()
