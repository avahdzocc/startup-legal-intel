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

### PublicCompanies (10,354 rows) — Currently publicly traded companies
- CIK (VARCHAR): Central Index Key, zero-padded to 10 digits (matches FormDIssuers.CIK directly)
- CompanyName (VARCHAR): Current company name
- Ticker (VARCHAR): Stock ticker symbol, e.g. 'AAPL', 'NVDA', 'GOOGL'
- Exchange (VARCHAR): 'Nasdaq', 'NYSE', 'OTC', or NULL

## Critical Join Logic
CIK links companies across tables. FormDIssuers.CIK is zero-padded to 10 digits.
S1Filings.CIK is NOT padded. To join them:
  FormDIssuers.CIK = RIGHT('0000000000' || S1Filings.CIK, 10)

PublicCompanies.CIK IS zero-padded. To join to FormDIssuers:
  FormDIssuers.CIK = PublicCompanies.CIK (direct match)
To join to S1Filings:
  PublicCompanies.CIK = RIGHT('0000000000' || S1Filings.CIK, 10)

FormDIssuers joins to FormDOffering and FormDSubmission via ACCESSIONNUMBER.

## Domain Knowledge
- Form D: Filed when a company makes a private, SEC-exempt securities offering
- S-1/F-1: Registration statement filed in anticipation of an IPO
- PublicCompanies: Companies currently trading on a stock exchange. A stronger signal than
  S-1 filing alone — an S-1 indicates IPO intent, but PublicCompanies confirms the company
  is actually trading today. Use PublicCompanies when the user asks about companies that
  "went public," "are publicly traded," or "are listed." Use S1Filings when they ask about
  IPO filings or IPO intent.
- A company appearing in S1Filings indicates it pursued an IPO
- CIK: Central Index Key — SEC's unique company identifier
- To analyze original filings only (not amendments): filter WHERE ISAMENDMENT = 'false'
- US states use 2-letter codes (CA, NY); filter with regexp_matches(STATEORCOUNTRY, '^[A-Z]{2}$')
- Numeric fields (TOTALOFFERINGAMOUNT, etc.) are stored as VARCHAR — cast to DOUBLE when needed
- Use NULLIF and TRY_CAST for safe numeric conversion: TRY_CAST(TOTALOFFERINGAMOUNT AS DOUBLE)
- When querying S1Filings for IPO matches, include ALL FormType values (S-1, S-1/A, F-1, F-1/A),
  not just originals. A company whose initial S-1 predates our data window may only appear via
  amendments. Use SELECT DISTINCT CIK FROM S1Filings without filtering on FormType.

## State of Location vs State of Incorporation
STATEORCOUNTRY records a company's physical location (principal office), NOT where it is
incorporated. JURISDICTIONOFINC records the state/country of incorporation.
- Delaware ranks low by physical location but is the #1 incorporation jurisdiction — most
  companies incorporate in DE for its favorable corporate law but are headquartered elsewhere.
- When state-level results show Delaware ranking low, note this distinction in the summary.
- If the user asks about incorporation trends, use JURISDICTIONOFINC instead of STATEORCOUNTRY.

## Important: Fund Vehicles vs Operating Companies
The INDUSTRYGROUPTYPE field contains BOTH operating company industries (Biotechnology,
Pharmaceuticals, etc.) AND "Pooled Investment Fund" which represents fund vehicles
(hedge funds, PE funds, VC funds) — NOT operating companies.
- When the user asks about "industries," "sectors," or "companies," EXCLUDE Pooled Investment
  Fund by default (WHERE INDUSTRYGROUPTYPE != 'Pooled Investment Fund') unless they
  specifically ask about funds.
- When the user asks about funds, venture capital, hedge funds, or PE, use the
  INVESTMENTFUNDTYPE column to distinguish: 'Venture Capital Fund', 'Hedge Fund',
  'Private Equity Fund', 'Other Investment Fund'.
- This distinction matters because fund vehicles massively outnumber and out-raise operating
  companies in the dataset, and a startup lawyer is typically interested in operating companies.

## Avoiding Aggregate Inflation
There are TWO sources of inflation to guard against:

### 1. JOIN inflation
FormDIssuers has MULTIPLE rows per filing (one per issuer/co-issuer). JOINing FormDOffering
to FormDIssuers before aggregating dollar amounts (SUM, AVG, MEDIAN on TOTALAMOUNTSOLD,
TOTALOFFERINGAMOUNT, etc.) will silently inflate the results because each issuer row
duplicates the offering's financial data.
- For financial aggregates (SUM, AVG, MEDIAN of dollar amounts): query FormDOffering ALONE
  without joining to FormDIssuers. All dollar columns live on FormDOffering.
- For company counts (COUNT DISTINCT CIK): JOIN to FormDIssuers is needed since CIK
  lives there. Do this in a separate subquery or CTE, not in the same query that sums dollars.
- If you need both dollar aggregates AND company counts, use a CTE or subquery to compute
  them independently, then combine.

### 2. Amendment inflation
Many companies (especially funds) file an original Form D then multiple amendments (D/A).
Each filing row has its own TOTALAMOUNTSOLD. Summing without filtering includes the same
fund's amount multiple times.
- When computing dollar aggregates (SUM, AVG, MEDIAN): ALWAYS filter WHERE ISAMENDMENT = 'false'
  to count only original filings, unless the user specifically asks about amendments.
- For counting distinct companies (COUNT DISTINCT CIK): amendments don't matter since
  DISTINCT handles deduplication.

### Example: correct pattern when you need BOTH dollar aggregates AND company counts by state
WRONG (JOIN inflation — SUM runs on duplicated rows):
  SELECT i.STATEORCOUNTRY, COUNT(DISTINCT i.CIK), SUM(TRY_CAST(o.TOTALAMOUNTSOLD AS DOUBLE))
  FROM FormDOffering o JOIN FormDIssuers i ON o.ACCESSIONNUMBER = i.ACCESSIONNUMBER
  WHERE o.ISAMENDMENT = 'false' GROUP BY i.STATEORCOUNTRY

CORRECT (CTEs keep dollar sums and company counts independent):
  WITH dollars AS (
      SELECT i.STATEORCOUNTRY, SUM(TRY_CAST(o.TOTALAMOUNTSOLD AS DOUBLE)) AS total_raised
      FROM FormDOffering o
      JOIN FormDIssuers i ON o.ACCESSIONNUMBER = i.ACCESSIONNUMBER
        AND i.IS_PRIMARYISSUER_FLAG = 'YES'
      WHERE o.ISAMENDMENT = 'false'
      GROUP BY i.STATEORCOUNTRY
  ),
  companies AS (
      SELECT i.STATEORCOUNTRY, COUNT(DISTINCT i.CIK) AS num_companies
      FROM FormDIssuers i
      JOIN FormDOffering o ON i.ACCESSIONNUMBER = o.ACCESSIONNUMBER
      GROUP BY i.STATEORCOUNTRY
  )
  SELECT d.STATEORCOUNTRY, c.num_companies, d.total_raised
  FROM dollars d JOIN companies c ON d.STATEORCOUNTRY = c.STATEORCOUNTRY

Always use this CTE pattern when a query needs both dollar aggregates and entity counts.

## Rules
- Generate ONLY SELECT statements. Never generate INSERT, UPDATE, DELETE, DROP, or ALTER.
- Use DuckDB SQL syntax (|| for concat, DOUBLE not FLOAT, regexp_matches for regex).
- For "top N" or ranked queries, use LIMIT matching what the user asked (default to 10-20).
- For list queries ("which companies," "show me all"), use LIMIT 500 to avoid truncating useful results.
- For aggregate queries (GROUP BY state, industry, etc.), no LIMIT needed — the result set is naturally small.
- When counting distinct companies, use DISTINCT CIK to avoid double-counting.
- When computing financial averages (AVG of dollar amounts), always include MEDIAN and COUNT
  alongside AVG. Financial data is heavily skewed by outliers, so median is more representative
  of the "typical" value. COUNT shows how many valid rows contributed to the calculation
  (since TRY_CAST returns NULL for non-numeric values like "Indefinite" and AVG/MEDIAN skip NULLs).
- Return ONLY the SQL query, no explanation or markdown formatting."""


def generate_sql(client, question, history=None):
    """Ask Claude to translate a natural language question into SQL.

    history: list of prior (question, sql) tuples for conversational context.
    """
    messages = []

    # Include recent conversation history so Claude can handle follow-ups
    if history:
        for prev_question, prev_sql in history[-3:]:
            messages.append({"role": "user", "content": prev_question})
            messages.append({"role": "assistant", "content": prev_sql})

    messages.append({"role": "user", "content": question})

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SCHEMA_PROMPT,
        messages=messages,
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
Keep your response to 2-4 sentences for simple results, up to a short paragraph for complex ones.
CRITICAL: Never use dollar signs ($) for currency — the output is rendered in a system that
interprets $ as LaTeX math delimiters. Write "USD 5.4 billion" or "5.4 billion dollars" instead.
Scope transparency: Always end your summary with a brief "Scope" note that states what the query
included or excluded and why. Examples:
  "Scope: Excludes pooled investment funds (hedge funds, PE, VC); includes only operating companies."
  "Scope: Includes all entity types. Note that LLC and LP counts include fund vehicles, which
   rarely IPO in their native form — filtering to operating companies only would change these rates."
  "Scope: Includes all Form D filers regardless of industry."
This lets the reader judge whether the analysis fits their question. Keep the scope note to 1-2
sentences. If nothing notable was filtered, a simple "Scope: All Form D filers included." suffices.""",
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\n\nSQL executed:\n{sql}\n\nResults:\n{result_text}"
            }
        ]
    )
    return response.content[0].text


def query(question, history=None):
    """
    Main entry point: takes a natural language question, returns a dict with:
      - sql: the generated SQL query
      - columns: list of column names
      - rows: list of result tuples
      - summary: plain English summary
      - error: error message if something went wrong (None on success)

    history: list of prior (question, sql) tuples for follow-up context.
    """
    client = anthropic.Anthropic()

    # Step 1: Generate SQL
    try:
        sql = generate_sql(client, question, history=history)
    except Exception as e:
        return {"sql": None, "columns": [], "rows": [], "summary": None,
                "error": f"Failed to generate SQL: {e}"}

    # Step 2: Execute (with safety checks)
    import re
    sql_stripped = re.sub(r'--.*$', '', sql, flags=re.MULTILINE).strip()
    sql_upper = sql_stripped.upper()
    blocked = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH", "COPY", "EXPORT", "IMPORT", "LOAD"]
    if any(kw in sql_upper for kw in blocked) or ";" in sql_stripped:
        return {"sql": sql, "columns": [], "rows": [], "summary": None,
                "error": "Safety check: only single SELECT queries are allowed."}

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
