#!/usr/bin/env python3
"""
03_build_qcew_county.py
=======================
Build the county x industry employment table (base-year employment shares
N_ic / N_c) from the QCEW "by area" quarterly county files.

Verified on sample files (Autauga and Chilton counties, 2025)
-------------------------------------------------------------
- One CSV per area; `area_fips` is the 5-digit county FIPS. Statewide, MSA and
  other area files sit in the same folder and are excluded here.
- agglvl_code 70 / own_code 0   = county total, all ownerships (denominator N_c)
- agglvl_code 71 / own_code 5   = county private total
- agglvl_code 74 / own_code 5   = private NAICS sector (e.g. "31-33")
- agglvl_code 75 / own_code 5   = private NAICS 3-digit (the paper's level)
- disclosure_code "N" = employment suppressed (reported as 0). We treat these as
  MISSING, not zero. disclosure_code "-" rows have zero establishments (a true 0).
- Suppression is heavy: in Chilton County, 52% of manufacturing employment is
  not visible at NAICS-3. The QA below quantifies this nationally.

Employment measure: mean of the (up to) 12 monthly employment levels in the year,
using only non-suppressed months. Industries suppressed in all months get NaN
(`suppressed_all = True`); downstream scripts decide how to treat them.

Output (long format), one row per county x (agglvl, ownership, industry):
    area_fips, agglvl_code, own_code, industry_code, emp_avg, n_months_valid
data/processed/qcew_county_industry_{year}.parquet (or .csv.gz)
output/qcew_qa/summary_{year}.txt

Usage
-----
    python3 scripts/03_build_qcew_county.py
    python3 scripts/03_build_qcew_county.py --qcew-dir data/raw/qcew/2023/2023.q1-q4.by_area
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

USECOLS = ["area_fips", "own_code", "industry_code", "agglvl_code", "year", "qtr",
           "disclosure_code", "month1_emplvl", "month2_emplvl", "month3_emplvl"]
KEEP = {("70", "0"), ("71", "5"), ("74", "5"), ("75", "5")}  # (agglvl, own)
TERRITORY_STATES = {"72", "78"}  # Puerto Rico, US Virgin Islands
MFG_NAICS3 = [str(n) for n in range(311, 340) if str(n) not in {"317", "318", "319", "328", "329", "338"}]


def is_county_fips(f: str, include_territories: bool) -> bool:
    if not re.fullmatch(r"\d{5}", f or ""):
        return False
    if f.endswith("000") or f.endswith("999"):  # statewide / unknown-undefined
        return False
    if not include_territories and f[:2] in TERRITORY_STATES:
        return False
    return True


def read_county_file(path: Path, include_territories: bool):
    d = pd.read_csv(path, usecols=USECOLS, dtype=str)
    d["area_fips"] = d["area_fips"].str.strip().str.zfill(5)
    if d.empty or not is_county_fips(d["area_fips"].iloc[0], include_territories):
        return None
    d = d[[(a, o) in KEEP for a, o in zip(d["agglvl_code"], d["own_code"])]]
    if d.empty:
        return None
    long = d.melt(id_vars=["area_fips", "own_code", "industry_code", "agglvl_code",
                           "qtr", "disclosure_code"],
                  value_vars=["month1_emplvl", "month2_emplvl", "month3_emplvl"],
                  value_name="emp")
    long["emp"] = pd.to_numeric(long["emp"], errors="coerce")
    long.loc[long["disclosure_code"] == "N", "emp"] = float("nan")  # suppressed
    g = long.groupby(["area_fips", "agglvl_code", "own_code", "industry_code"],
                     as_index=False)["emp"].agg(emp_avg="mean", n_months_valid="count")
    return g, d["year"].iloc[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qcew-dir", type=Path,
                    default=ROOT / "data/raw/qcew/2024/2024.q1-q4.by_area")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data/processed")
    ap.add_argument("--qa-dir", type=Path, default=ROOT / "output/qcew_qa")
    ap.add_argument("--include-territories", action="store_true",
                    help="keep Puerto Rico / USVI (excluded by default)")
    a = ap.parse_args()

    files = sorted(a.qcew_dir.glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files in {a.qcew_dir}")
    print(f"Found {len(files):,} files in {a.qcew_dir}")

    parts, years, skipped = [], set(), 0
    for i, f in enumerate(files, 1):
        m = re.search(r"(?<!\d)(\d{5})(?!\d)", f.name)  # cheap pre-filter on file name
        if m and not is_county_fips(m.group(1), a.include_territories):
            skipped += 1
            continue
        res = read_county_file(f, a.include_territories)
        if res is None:
            skipped += 1
            continue
        parts.append(res[0])
        years.add(res[1])
        if i % 500 == 0:
            print(f"  {i:,}/{len(files):,} files read", flush=True)
    if not parts:
        sys.exit("No county files were read.")
    if len(years) != 1:
        sys.exit(f"Expected one year in the data, found {sorted(years)}")
    year = years.pop()

    df = pd.concat(parts, ignore_index=True)
    df["suppressed_all"] = df["emp_avg"].isna()

    # ----- save -----
    a.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import pyarrow  # noqa: F401
        out = a.out_dir / f"qcew_county_industry_{year}.parquet"
        df.to_parquet(out, index=False)
    except ImportError:
        out = a.out_dir / f"qcew_county_industry_{year}.csv.gz"
        df.to_csv(out, index=False, compression="gzip")

    # ----- QA -----
    tot = df[(df.agglvl_code == "70") & (df.own_code == "0")].set_index("area_fips")["emp_avg"]
    priv = df[(df.agglvl_code == "71") & (df.own_code == "5")].set_index("area_fips")["emp_avg"]
    n3 = df[(df.agglvl_code == "75") & (df.own_code == "5")]
    sec = df[(df.agglvl_code == "74") & (df.own_code == "5") & (df.industry_code == "31-33")] \
        .set_index("area_fips")["emp_avg"]
    mfg3 = (n3[n3.industry_code.isin(MFG_NAICS3)].groupby("area_fips")["emp_avg"].sum(min_count=1))
    cov = pd.DataFrame({"sector": sec, "n3_sum": mfg3}).dropna(subset=["sector"])
    cov = cov[cov["sector"] > 0]
    cov["n3_sum"] = cov["n3_sum"].fillna(0.0)
    cov["coverage"] = (cov["n3_sum"] / cov["sector"]).clip(upper=1.0)

    L = [f"QCEW COUNTY BUILD QA ({year})", "=" * 60,
         f"Files read: {len(parts):,} counties (skipped {skipped:,} non-county / territory files)",
         f"Total covered employment (sum over counties): {tot.sum():,.0f}",
         f"Private employment share of total: {priv.sum() / tot.sum():.1%}",
         f"Counties missing a total-employment row: {len(set(df.area_fips) - set(tot.index))}",
         "",
         "NAICS-3 suppression (private):",
         f"  industry-county cells: {len(n3):,}; fully suppressed: {n3['suppressed_all'].mean():.1%}",
         "",
         "Manufacturing visible at NAICS-3 (sum of disclosed 3-digit / sector 31-33):",
         f"  counties with manufacturing: {len(cov):,}",
         f"  employment-weighted coverage: "
         f"{(cov['n3_sum'].sum() / cov['sector'].sum()):.1%}",
         f"  median county coverage: {cov['coverage'].median():.1%}",
         f"  counties with coverage < 50%: {(cov['coverage'] < 0.5).mean():.1%}"]
    text = "\n".join(L)
    a.qa_dir.mkdir(parents=True, exist_ok=True)
    (a.qa_dir / f"summary_{year}.txt").write_text(text + "\n")
    print(f"Wrote {out} ({len(df):,} rows)\n")
    print(text)


if __name__ == "__main__":
    main()
