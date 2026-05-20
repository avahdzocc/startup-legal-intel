"""
Phase 2: Validate that our DuckDB data reproduces the original T-SQL query results.

This script runs both research question queries from the academic project
against the local DuckDB database and prints the results for comparison
with the original Navicat output.

Usage:
    python3 scripts/02_validate_queries.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "sec_data.duckdb"


def run_query(con, title, sql):
    """Execute a query and print results as a formatted table."""
    print("=" * 90)
    print(title)
    print("=" * 90)
    result = con.execute(sql)
    columns = [desc[0] for desc in result.description]

    # Calculate column widths from headers and data
    rows = result.fetchall()
    widths = [len(c) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # Print header
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    print(header)
    print("-" * len(header))

    # Print rows
    for row in rows:
        print(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))

    print(f"\n({len(rows)} rows)\n")


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    # ------------------------------------------------------------------
    # Research Question 1: IPO rates by state
    #
    # Logic (matching original T-SQL):
    #   - Subquery: distinct CIKs from FormDIssuers (one row per company)
    #   - LEFT JOIN to distinct CIKs from S1Filings (companies that IPO'd)
    #   - CIK padding: S1Filings CIK gets zero-padded to 10 chars for the join
    #   - Filter out foreign country codes (contain digits)
    #   - Only states with >= 5 companies
    # ------------------------------------------------------------------
    q1 = """
    SELECT
        I.STATEORCOUNTRY,
        COUNT(CASE WHEN S1.CIK IS NOT NULL THEN 1 ELSE NULL END)
            AS "Company IPOs (2009-2025)",
        COUNT(*)
            AS "Total Companies Per State (2014-2025)",
        CAST(COUNT(CASE WHEN S1.CIK IS NOT NULL THEN 1 ELSE NULL END) AS DOUBLE)
            / COUNT(*) * 100
            AS "IPO Rate Per State %"
    FROM
        (SELECT DISTINCT CIK, STATEORCOUNTRY FROM FormDIssuers) AS I
    LEFT JOIN
        (SELECT DISTINCT CIK FROM S1Filings) AS S1
        ON I.CIK = RIGHT('0000000000' || S1.CIK, 10)
    WHERE
        regexp_matches(I.STATEORCOUNTRY, '^[A-Z]{2}$')
        AND I.STATEORCOUNTRY NOT IN ('XX')
    GROUP BY
        I.STATEORCOUNTRY
    HAVING
        COUNT(*) >= 5
    ORDER BY
        "IPO Rate Per State %" DESC
    """

    run_query(con, "RESEARCH QUESTION 1: IPO Rates by State", q1)

    # ------------------------------------------------------------------
    # Research Question 2: IPO rates by industry
    #
    # Logic (matching original T-SQL):
    #   - Subquery: distinct CIKs joined with their industry from FormDOffering
    #   - INNER JOIN issuers to offerings on AccessionNumber
    #   - Filter: only original filings (ISAMENDMENT = 'false')
    #   - LEFT JOIN to S1Filings for IPO match
    #   - Group by industry type
    #
    # Note: the original query filtered ISAMENDMENT = 'FALSE' (uppercase).
    # DuckDB string comparison is case-sensitive by default, so we use
    # UPPER() to handle both 'false' and 'FALSE' in the raw data.
    # ------------------------------------------------------------------
    q2 = """
    SELECT
        DistinctCompany.INDUSTRYGROUPTYPE AS "Industry Type",
        COUNT(CASE WHEN S1.CIK IS NOT NULL THEN 1 ELSE NULL END)
            AS "Company IPOs (2009-2025)",
        COUNT(*)
            AS "Companies Per Industry (2014-2025)",
        CAST(COUNT(CASE WHEN S1.CIK IS NOT NULL THEN 1 ELSE NULL END) AS DOUBLE)
            / COUNT(*) * 100
            AS "IPO Rate By Industry %"
    FROM
        (
            SELECT DISTINCT I.CIK, O.INDUSTRYGROUPTYPE
            FROM FormDIssuers AS I
            INNER JOIN FormDOffering AS O
                ON O.ACCESSIONNUMBER = I.ACCESSIONNUMBER
            WHERE UPPER(O.ISAMENDMENT) = 'FALSE'
        ) AS DistinctCompany
    LEFT JOIN
        (SELECT DISTINCT CIK FROM S1Filings) AS S1
        ON DistinctCompany.CIK = RIGHT('0000000000' || S1.CIK, 10)
    GROUP BY
        DistinctCompany.INDUSTRYGROUPTYPE
    ORDER BY
        "IPO Rate By Industry %" DESC
    """

    run_query(con, "RESEARCH QUESTION 2: IPO Rates by Industry", q2)

    con.close()
    print("Validation complete. Compare these results against your original paper.")


if __name__ == "__main__":
    main()
