#!/usr/bin/env python3
"""
04_convert_laus.py
==================
Convert the BLS LAUS county flat file (tab-delimited text, ~340 MB, all measures,
1990 onward) into a small tidy CSV of county unemployment rates.

Format (verified on the uploaded file)
--------------------------------------
Columns: series_id, year, period, value, footnote_codes. Fields are padded with
spaces and lines end in CRLF. series_id looks like LAUCN010010000000003:
    "LAUCN" + 5-digit county FIPS + ... + 2-digit measure code
Measure codes: 03 unemployment rate, 04 unemployment, 05 employment, 06 labor force.
"CN" = county, NOT seasonally adjusted (so county x calendar-month effects or
12-month differences are needed in the regressions).
period M01-M12 are months; M13 is the annual average (dropped).

Things you should know about this file
--------------------------------------
- Connecticut appears as 9 planning regions (09110-09190), not the 8 old counties,
  in ALL years including 2023. Check that your QCEW county codes for Connecticut
  use the same codes before merging.
- October 2025 (M10) is "-" (missing) for every county, footnote X. This is a hole in
  the outcome series, not a data error; the regressions must handle it explicitly.
- 2026 values carry footnote P (preliminary).
- Puerto Rico (state FIPS 72, 78 municipios) is excluded by default, as in 03.

Output
------
data/processed/laus_county_unemployment.csv
    fips, state_fips, year, month, date, unemp_rate, footnote_codes
output/laus_qa/summary.txt

Usage
-----
    python3 scripts/04_convert_laus.py --input data/raw/la_data_county.txt
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MEASURES = {"03": "unemp_rate", "04": "unemployed", "05": "employed", "06": "labor_force"}


def find_input(arg):
    if arg:
        return arg
    hits = sorted((ROOT / "data").rglob("la_data_county*.txt"))
    if not hits:
        sys.exit("Could not find la_data_county*.txt under data/. Use --input PATH.")
    print(f"Using input: {hits[0]}")
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=None)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data/processed/laus_county_unemployment.csv")
    ap.add_argument("--qa-dir", type=Path, default=ROOT / "output/laus_qa")
    ap.add_argument("--min-year", type=int, default=2022,
                    help="first year kept (2022 allows 12-month changes starting in 2023)")
    ap.add_argument("--measures", nargs="+", default=["03"], choices=sorted(MEASURES),
                    help="LAUS measure codes to keep (default: 03 = unemployment rate)")
    ap.add_argument("--include-territories", action="store_true")
    a = ap.parse_args()

    src = find_input(a.input)
    parts = []
    for ch in pd.read_csv(src, sep="\t", dtype=str, skipinitialspace=True,
                          chunksize=1_000_000):
        ch.columns = [c.strip() for c in ch.columns]
        for c in ch.columns:
            ch[c] = ch[c].str.strip()
        ch = ch[ch["year"].astype(int) >= a.min_year]
        ch = ch[ch["period"] != "M13"]
        ch["measure"] = ch["series_id"].str[-2:]
        ch = ch[ch["measure"].isin(a.measures)]
        ch["fips"] = ch["series_id"].str[5:10]
        if not a.include_territories:
            ch = ch[~ch["fips"].str.startswith("72")]
        parts.append(ch)
    df = pd.concat(parts, ignore_index=True)
    if df.empty:
        sys.exit("No rows left after filtering - check --input and --min-year.")

    df["month"] = df["period"].str[1:].astype(int)
    df["year"] = df["year"].astype(int)
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
    df["state_fips"] = df["fips"].str[:2]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # "-" -> NaN
    df["footnote_codes"] = df["footnote_codes"].fillna("")

    # one column per measure (wide), keyed by county-month
    keys = ["fips", "state_fips", "year", "month", "date"]
    # unstack (not pivot_table) so months with a missing value stay as NaN rows
    wide = (df.drop_duplicates(keys + ["measure"])
              .set_index(keys + ["measure"])["value"].unstack("measure")
              .rename(columns=MEASURES).reset_index())
    foot = (df[df["measure"] == a.measures[0]][keys + ["footnote_codes"]]
            .drop_duplicates(keys))
    out = wide.merge(foot, on=keys, how="left").sort_values(["fips", "date"])
    out.columns.name = None

    a.out.parent.mkdir(parents=True, exist_ok=True)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(a.out, index=False)

    # ---- QA ----
    first = MEASURES[a.measures[0]]
    miss = out[out[first].isna()]
    L = ["LAUS CONVERSION QA", "=" * 60,
         f"Rows written: {len(out):,}  ({out['fips'].nunique():,} counties)",
         f"Date range: {out['date'].min()} to {out['date'].max()}",
         f"Counties per year: " + ", ".join(f"{y}: {g['fips'].nunique():,}"
                                            for y, g in out.groupby("year")),
         f"Missing {first} observations: {len(miss):,}"]
    if len(miss):
        by = miss.groupby("date")["fips"].nunique()
        L.append("  months with missing values (counties affected): " +
                 ", ".join(f"{d} ({n:,})" for d, n in by.items()))
    ct = sorted(set(out.loc[out["state_fips"] == "09", "fips"]))
    L.append(f"Connecticut codes: {ct}")
    L.append(f"Preliminary (P) rows: {(out['footnote_codes'] == 'P').sum():,}")
    text = "\n".join(L)
    a.qa_dir.mkdir(parents=True, exist_ok=True)
    (a.qa_dir / "summary.txt").write_text(text + "\n")
    print(f"Wrote {a.out}\n")
    print(text)


if __name__ == "__main__":
    main()
