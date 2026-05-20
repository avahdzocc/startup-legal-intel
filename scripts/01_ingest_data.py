"""
Phase 1: Ingest raw SEC data files into a local DuckDB database.

This script reads:
  - Form D quarterly TSV files (ISSUERS, OFFERING, FORMDSUBMISSION) from ~/Downloads/form_d_data/
  - S1 filing CSV from ~/Downloads/edgar_index_data/s1_filings_all.csv

It creates a single DuckDB database file at: startup-legal-intel/db/sec_data.duckdb
with four tables mirroring the original Navicat schema (but keeping ALL columns).

Usage:
    python3 scripts/01_ingest_data.py
"""

import duckdb
from pathlib import Path

# --- Configuration ---
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "db" / "sec_data.duckdb"

FORM_D_DIR = Path.home() / "Downloads" / "form_d_data"
S1_CSV = Path.home() / "Downloads" / "edgar_index_data" / "s1_filings_all.csv"

# Glob pattern: each quarter has a subfolder like "2025Q4_d" containing the TSVs
ISSUERS_GLOB = str(FORM_D_DIR / "*" / "*" / "ISSUERS.tsv")
OFFERING_GLOB = str(FORM_D_DIR / "*" / "*" / "OFFERING.tsv")
SUBMISSION_GLOB = str(FORM_D_DIR / "*" / "*" / "FORMDSUBMISSION.tsv")


def main():
    print(f"Creating database at: {DB_PATH}\n")

    # Connect to a persistent DuckDB file (created if it doesn't exist)
    con = duckdb.connect(str(DB_PATH))

    # --- Table 1: FormDIssuers ---
    # All quarterly ISSUERS.tsv files combined into one table.
    # DuckDB's read_csv_auto handles the glob, detects tab delimiters, and unions all files.
    print("Loading FormDIssuers...")
    con.execute("DROP TABLE IF EXISTS FormDIssuers")
    con.execute(f"""
        CREATE TABLE FormDIssuers AS
        SELECT * FROM read_csv_auto('{ISSUERS_GLOB}',
            delim = '\t',
            header = true,
            all_varchar = true,
            union_by_name = true
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM FormDIssuers").fetchone()[0]
    print(f"  -> {count:,} rows loaded\n")

    # --- Table 2: FormDOffering ---
    print("Loading FormDOffering...")
    con.execute("DROP TABLE IF EXISTS FormDOffering")
    con.execute(f"""
        CREATE TABLE FormDOffering AS
        SELECT * FROM read_csv_auto('{OFFERING_GLOB}',
            delim = '\t',
            header = true,
            all_varchar = true,
            union_by_name = true
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM FormDOffering").fetchone()[0]
    print(f"  -> {count:,} rows loaded\n")

    # --- Table 3: FormDSubmission ---
    print("Loading FormDSubmission...")
    con.execute("DROP TABLE IF EXISTS FormDSubmission")
    con.execute(f"""
        CREATE TABLE FormDSubmission AS
        SELECT * FROM read_csv_auto('{SUBMISSION_GLOB}',
            delim = '\t',
            header = true,
            all_varchar = true,
            union_by_name = true
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM FormDSubmission").fetchone()[0]
    print(f"  -> {count:,} rows loaded\n")

    # --- Table 4: S1Filings ---
    print("Loading S1Filings...")
    con.execute("DROP TABLE IF EXISTS S1Filings")
    con.execute(f"""
        CREATE TABLE S1Filings AS
        SELECT * FROM read_csv_auto('{S1_CSV}',
            header = true,
            all_varchar = true
        )
    """)
    count = con.execute("SELECT COUNT(*) FROM S1Filings").fetchone()[0]
    print(f"  -> {count:,} rows loaded\n")

    # --- Verification: print column names for each table ---
    print("=" * 60)
    print("DATABASE SUMMARY")
    print("=" * 60)
    for table in ["FormDIssuers", "FormDOffering", "FormDSubmission", "S1Filings"]:
        cols = con.execute(f"DESCRIBE {table}").fetchall()
        row_count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"\n{table} ({row_count:,} rows, {len(cols)} columns):")
        for col_name, col_type, *_ in cols:
            print(f"  {col_name}: {col_type}")

    # --- Quick sanity check: sample a few issuers ---
    print("\n" + "=" * 60)
    print("SAMPLE: 5 rows from FormDIssuers")
    print("=" * 60)
    sample = con.execute("""
        SELECT CIK, ENTITYNAME, STATEORCOUNTRY, ENTITYTYPE
        FROM FormDIssuers
        LIMIT 5
    """).fetchall()
    for row in sample:
        print(f"  CIK={row[0]}, Name={row[1]}, State={row[2]}, Type={row[3]}")

    con.close()
    print(f"\nDone. Database saved to: {DB_PATH}")
    print(f"File size: {DB_PATH.stat().st_size / (1024*1024):.1f} MB")


if __name__ == "__main__":
    main()
