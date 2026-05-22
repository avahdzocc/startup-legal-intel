# Startup Legal Intelligence Agent

A natural language interface for querying SEC filing data, built for startup lawyers. Ask questions in plain English and get back data-driven insights with full SQL transparency.

**Powered by Claude (Anthropic API) + DuckDB.**

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Try It

The live demo is available now — no setup required:

**[startup-legal-intel-8cg6w7f79bg7jwbg6xai6s.streamlit.app](https://startup-legal-intel-8cg6w7f79bg7jwbg6xai6s.streamlit.app/)**

Ask any question about SEC filings in plain English. The tool translates it to SQL, queries 600K+ filings, and returns a plain-English summary with the generated query and raw data.

## What It Does

This tool lets a startup lawyer query 600K+ SEC Form D filings and 68K S-1 registrations using natural language. It translates questions into SQL, executes them against a local DuckDB database, and returns plain-English summaries with legal context.

**Example queries:**
- "Which states have the highest IPO rates?"
- "Compare IPO rates: California vs New York vs Texas"
- "Which biotech companies that filed Form D are currently trading on NASDAQ?"
- "What is the average offering size for pharma companies?"
- "Which entity types are most likely to IPO?"

Each response includes:
- A plain-English summary with practitioner-relevant takeaways
- The generated SQL query (expandable, for full transparency)
- Raw data table (expandable, as a Pandas DataFrame)
- A scope note explaining what was included/excluded and why

## Architecture

```
User Question (natural language)
        |
        v
  Claude API  -->  Generates DuckDB SQL
        |
        v
  DuckDB (local)  -->  Executes query against SEC data
        |
        v
  Claude API  -->  Summarizes results in plain English
        |
        v
  Streamlit UI  -->  Displays summary + SQL + raw data
```

**Key design decisions:**
- **DuckDB** for the database layer: serverless, columnar storage optimized for analytical queries, native CSV/TSV ingestion
- **Claude API directly** (no LangChain): leaner code, no unnecessary abstraction
- **Read-only database access**: the AI can never modify the data
- **Write-blocking safety check**: rejects any non-SELECT SQL
- **Conversational context**: follow-up questions reference prior queries, enabling iterative analysis

## Data Sources

| Table | Source | Rows | Description |
|-------|--------|------|-------------|
| FormDIssuers | [SEC Form D Data Sets](https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets) | 603K | Company info from private offering filings |
| FormDOffering | Same | 594K | Offering details: industry, amounts, fund type |
| FormDSubmission | Same | 594K | Filing metadata and dates |
| S1Filings | [EDGAR Full Index](https://www.sec.gov/Archives/edgar/full-index/) | 68K | IPO registration statements (S-1/F-1) |
| PublicCompanies | [EDGAR Company Tickers](https://www.sec.gov/files/company_tickers_exchange.json) | 10K | Currently traded companies with ticker and exchange |

## Development Setup

The following instructions are for rebuilding the tool locally. To use the deployed app, visit the [live demo](https://startup-legal-intel-8cg6w7f79bg7jwbg6xai6s.streamlit.app/) above.

### Prerequisites (local development only)
- Python 3.10+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Raw SEC data files (see Data Preparation below)

### Installation

```bash
git clone https://github.com/yourusername/startup-legal-intel.git
cd startup-legal-intel
pip install -r requirements.txt
```

### Data Preparation

1. Download Form D quarterly data from the [SEC Form D Data Sets page](https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets) and extract to `~/Downloads/form_d_data/`
2. Download S-1 filing index data from [EDGAR Full Index](https://www.sec.gov/Archives/edgar/full-index/) and save to `~/Downloads/edgar_index_data/s1_filings_all.csv`
3. Run the ingestion scripts in order:

```bash
python scripts/01_ingest_data.py       # Load Form D + S-1 data into DuckDB
python scripts/04_add_tickers.py       # Add current public company tickers
python scripts/02_validate_queries.py  # Verify data integrity
```

### API Key Setup

```bash
python scripts/setup_key.py  # Securely saves your key to .env
```

### Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

## Project Structure

```
startup-legal-intel/
  app.py                          # Streamlit chat interface
  requirements.txt                # Python dependencies
  .env                            # API key (git-ignored)
  .gitignore
  db/
    sec_data.duckdb               # Local database (git-ignored)
  scripts/
    01_ingest_data.py             # Phase 1: Ingest raw SEC files into DuckDB
    02_validate_queries.py        # Phase 2: Validate queries against known results
    03_ai_translator.py           # Phase 3: Standalone translator test
    04_add_tickers.py             # Add EDGAR public company tickers
    ai_translator_module.py       # Core module: NL -> SQL -> summary
    setup_key.py                  # One-time API key setup
```

## Domain-Aware Prompt Engineering

The AI translator includes domain knowledge specific to SEC data and startup law practice:

- **Fund vehicle vs. operating company distinction**: Automatically excludes pooled investment funds (hedge funds, PE, VC) from industry queries, since a startup lawyer typically cares about operating companies
- **Aggregate inflation prevention**: Uses CTE patterns to avoid double-counting from multi-issuer filings and amendment filings
- **State of location vs. incorporation**: Distinguishes between STATEORCOUNTRY (physical HQ) and JURISDICTIONOFINC (where incorporated), noting that Delaware dominates incorporation but ranks low by HQ location
- **Scope transparency**: Every response includes a scope note explaining what was included or excluded, enabling the user to assess whether the analysis fits their question
- **IPO proxy methodology**: Explains that S-1 filing is a proxy for IPO intent, while PublicCompanies data confirms current trading status

## Built With

- [Claude API](https://docs.anthropic.com/) (Anthropic) - Natural language to SQL translation and result summarization
- [DuckDB](https://duckdb.org/) - Local analytical database
- [Streamlit](https://streamlit.io/) - Chat interface
- SEC EDGAR public data

## Author

Ava Occhialini
