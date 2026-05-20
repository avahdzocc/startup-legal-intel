"""
Add EDGAR company tickers data to the DuckDB database.

This adds a PublicCompanies table mapping CIK to ticker symbol and exchange
for all currently publicly traded companies. Joins to existing tables via CIK.

Source: https://www.sec.gov/files/company_tickers_exchange.json

Usage:
    python3 scripts/04_add_tickers.py
"""

import duckdb
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "db" / "sec_data.duckdb"
TICKERS_JSON = Path.home() / "Downloads" / "edgar_index_data" / "company_tickers_exchange.json"


def main():
    with open(TICKERS_JSON) as f:
        data = json.load(f)

    # Data is in columnar format: {"fields": [...], "data": [[...], ...]}
    fields = data["fields"]  # ['cik', 'name', 'ticker', 'exchange']
    rows = data["data"]

    print(f"Loaded {len(rows):,} publicly traded companies from SEC")

    con = duckdb.connect(str(DB_PATH))

    # Create table — CIK is zero-padded to 10 digits to match FormDIssuers format
    con.execute("DROP TABLE IF EXISTS PublicCompanies")
    con.execute("""
        CREATE TABLE PublicCompanies (
            CIK VARCHAR,
            CompanyName VARCHAR,
            Ticker VARCHAR,
            Exchange VARCHAR
        )
    """)

    # Insert with zero-padded CIK
    for row in rows:
        cik_padded = str(row[0]).zfill(10)
        con.execute(
            "INSERT INTO PublicCompanies VALUES (?, ?, ?, ?)",
            [cik_padded, row[1], row[2], row[3]]
        )

    count = con.execute("SELECT COUNT(*) FROM PublicCompanies").fetchone()[0]
    print(f"Loaded {count:,} rows into PublicCompanies table")

    # Quick validation: how many match our Form D issuers?
    matches = con.execute("""
        SELECT COUNT(DISTINCT i.CIK)
        FROM FormDIssuers i
        JOIN PublicCompanies p ON i.CIK = p.CIK
    """).fetchone()[0]
    print(f"  {matches:,} Form D issuers are currently publicly traded")

    # How many match S1 filers?
    s1_matches = con.execute("""
        SELECT COUNT(DISTINCT p.CIK)
        FROM PublicCompanies p
        JOIN S1Filings s ON p.CIK = RIGHT('0000000000' || s.CIK, 10)
    """).fetchone()[0]
    print(f"  {s1_matches:,} S-1 filers are currently publicly traded")

    # Exchange breakdown
    print("\nExchange breakdown:")
    exchanges = con.execute("""
        SELECT Exchange, COUNT(*) as cnt
        FROM PublicCompanies
        GROUP BY Exchange
        ORDER BY cnt DESC
    """).fetchall()
    for exch, cnt in exchanges:
        print(f"  {exch}: {cnt:,}")

    con.close()
    print(f"\nDone. PublicCompanies table added to {DB_PATH}")


if __name__ == "__main__":
    main()
