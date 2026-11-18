#!/usr/bin/env python3
"""
02_build_trade_panel.py
=======================
Build the clean HS10 x country x month trade panel from the Census API chunks.

What the chunks contain (verified on sample chunks, Feb 2025)
-------------------------------------------------------------
CTY_CODE has three kinds of rows besides individual countries:
  "-"                total across all countries for that HS10
  "1XXX"..."7XXX"    regional aggregates
  "0003"..."0028"    country groupings (blocs)
Individual countries are numeric codes >= 1000 (e.g. 1220 Canada, 5700 China).
In both sample chunks the country rows sum exactly to the "-" total, so we keep
ONLY country rows (4 digits, first digit 1-9) and drop everything else. Summing
without this filter would multiply-count imports (about 4-5x in the samples).

This script re-checks that reconciliation for every month and reports it.

Inputs
------
data/raw/trade/chunks/trade_YYYY_MM_CH.csv
data/processed/hs10_naics_map.csv           (from 01_build_concordance.py)

Outputs
-------
data/processed/trade_panel/trade_YYYY_MM.parquet   (or .csv.gz if pyarrow is absent)
output/trade_panel_qa/monthly_summary.csv          month-level aggregates + checks
output/trade_panel_qa/summary.txt

Usage
-----
    python3 scripts/02_build_trade_panel.py
    python3 scripts/02_build_trade_panel.py --years 2023 2024 2025 2026 --overwrite
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

RAW_COLS = ["I_COMMODITY", "CTY_CODE", "GEN_VAL_MO", "CAL_DUT_MO", "GEN_QY1_MO"]
EXPECTED = {c for c in range(1, 100) if c != 77}  # chapter 77 is reserved (no data)
LAST_MONTH_2026 = 3     # data available through March 2026

MAP_COLS = ["hs10", "naics3", "naics4", "bea_sector", "end_use", "special_chapter",
            "non_industry_code", "in_paper_sample", "use_in_industry_agg"]

PAPER_CHINA_DEC25 = 29.2  # Figure 6, for the QA printout


def months_for(year: int):
    return range(1, (LAST_MONTH_2026 if year == 2026 else 12) + 1)


def have_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def save_month(df: pd.DataFrame, stem: Path, use_parquet: bool) -> Path:
    stem.parent.mkdir(parents=True, exist_ok=True)
    if use_parquet:
        path = stem.with_suffix(".parquet")
        df.to_parquet(path, index=False)
    else:
        path = stem.with_suffix(".csv.gz")
        df.to_csv(path, index=False, compression="gzip")
    return path


def load_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        sys.exit(f"Missing {path}. Run 01_build_concordance.py first.")
    m = pd.read_csv(path, dtype={"hs10": str, "naics3": str, "naics4": str})
    return m[MAP_COLS].drop_duplicates("hs10")


def read_month(chunk_dir: Path, yr: int, mo: int):
    files = sorted(chunk_dir.glob(f"trade_{yr}_{mo:02d}_*.csv"))
    parts, bad, present = [], 0, set()
    for f in files:
        try:
            d = pd.read_csv(f, usecols=RAW_COLS,
                            dtype={"I_COMMODITY": str, "CTY_CODE": str})
        except Exception:
            bad += 1
            continue
        present.add(int(f.stem.split("_")[-1]))
        if len(d):
            parts.append(d)
    missing = sorted(EXPECTED - present)
    if not parts:
        return None, missing, bad
    return pd.concat(parts, ignore_index=True), missing, bad


def process_month(raw: pd.DataFrame, cmap: pd.DataFrame):
    raw = raw.rename(columns={"I_COMMODITY": "hs10", "CTY_CODE": "cty_code",
                              "GEN_VAL_MO": "value", "CAL_DUT_MO": "duty",
                              "GEN_QY1_MO": "qty"})
    raw["hs10"] = raw["hs10"].str.strip().str.zfill(10)
    raw["cty_code"] = raw["cty_code"].str.strip()
    for c in ("value", "duty", "qty"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    n_dup_dropped = int(raw.duplicated().sum())
    raw = raw.drop_duplicates()

    is_total = raw["cty_code"] == "-"
    is_country = raw["cty_code"].str.fullmatch(r"[1-9]\d{3}").fillna(False)
    totals = raw[is_total].groupby("hs10")[["value", "duty"]].sum()
    ctry = raw[is_country].copy()

    # Reconciliation: country rows vs the "-" total, per HS10
    cs = ctry.groupby("hs10")[["value", "duty"]].sum()
    rec = totals.join(cs, how="outer", lsuffix="_tot", rsuffix="_cty").fillna(0.0)
    rec["bad_value"] = (rec["value_tot"] - rec["value_cty"]).abs() > 1.0
    rec["bad_duty"] = (rec["duty_tot"] - rec["duty_cty"]).abs() > 1.0
    n_dup_keys = int(ctry.duplicated(["hs10", "cty_code"]).sum())

    ctry = ctry.merge(cmap, on="hs10", how="left")
    ctry["in_map"] = ctry["naics3"].notna() | ctry["special_chapter"].notna()
    for c in ("special_chapter", "non_industry_code", "in_paper_sample",
              "use_in_industry_agg"):
        ctry[c] = ctry[c].fillna(False).astype(bool)
    ctry["tariff_r"] = (ctry["duty"] / ctry["value"]).where(ctry["value"] > 0)

    stats = {
        "n_country_rows": len(ctry),
        "n_hs10": ctry["hs10"].nunique(),
        "value_country": ctry["value"].sum(),
        "duty_country": ctry["duty"].sum(),
        "value_total_rows": totals["value"].sum(),
        "duty_total_rows": totals["duty"].sum(),
        "hs10_value_mismatch": int(rec["bad_value"].sum()),
        "hs10_duty_mismatch": int(rec["bad_duty"].sum()),
        "n_hs10_checked": len(rec),
        "dup_rows_dropped": n_dup_dropped,
        "dup_country_keys": n_dup_keys,
        "rows_not_in_map": int((~ctry["in_map"]).sum()),
        "value_not_in_map": ctry.loc[~ctry["in_map"], "value"].sum(),
        "negative_value_rows": int((ctry["value"] < 0).sum()),
        "aetr_world_pct": 100 * ctry["duty"].sum() / ctry["value"].sum()
        if ctry["value"].sum() else float("nan"),
    }
    china = ctry[ctry["cty_code"] == "5700"]
    stats["aetr_china_pct"] = (100 * china["duty"].sum() / china["value"].sum()
                               if china["value"].sum() else float("nan"))
    out_cols = ["hs10", "cty_code", "value", "duty", "qty", "tariff_r", "naics3",
                "naics4", "bea_sector", "end_use", "special_chapter",
                "non_industry_code", "in_paper_sample", "use_in_industry_agg"]
    return ctry[out_cols], stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunk-dir", type=Path, default=ROOT / "data/raw/trade/chunks")
    ap.add_argument("--map", type=Path, default=ROOT / "data/processed/hs10_naics_map.csv")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data/processed/trade_panel")
    ap.add_argument("--qa-dir", type=Path, default=ROOT / "output/trade_panel_qa")
    ap.add_argument("--years", type=int, nargs="+", default=[2023, 2024, 2025, 2026])
    ap.add_argument("--overwrite", action="store_true",
                    help="rebuild months that already have an output file")
    a = ap.parse_args()

    cmap = load_map(a.map)
    use_parquet = have_parquet()
    print(f"Output format: {'parquet' if use_parquet else 'csv.gz (install pyarrow for parquet)'}")

    rows = []
    for yr in a.years:
        for mo in months_for(yr):
            tag = f"{yr}-{mo:02d}"
            stem = a.out_dir / f"trade_{yr}_{mo:02d}"
            raw, missing_ch, n_bad = read_month(a.chunk_dir, yr, mo)
            if raw is None:
                print(f"{tag}: no data - skipped")
                continue
            ctry, st = process_month(raw, cmap)
            st.update({"month": tag, "n_missing_chapters": len(missing_ch),
                       "missing_chapters": " ".join(f"{c:02d}" for c in missing_ch),
                       "complete": not missing_ch, "n_unreadable": n_bad})
            done = any(stem.with_suffix(s).exists() for s in (".parquet", ".csv.gz"))
            if done and not a.overwrite:
                note = "exists (kept)"
            else:
                save_month(ctry, stem, use_parquet)
                note = "saved"
            warn = []
            if missing_ch:
                warn.append("INCOMPLETE, missing chapters " + " ".join(f"{c:02d}" for c in missing_ch))
            if st["hs10_value_mismatch"]:
                warn.append(f"{st['hs10_value_mismatch']} HS10 fail value reconciliation")
            print(f"{tag}: {len(ctry):>9,} country rows | AETR {st['aetr_world_pct']:5.2f}% "
                  f"| China {st['aetr_china_pct']:5.2f}% | {note}"
                  + (f" | WARN: {'; '.join(warn)}" if warn else ""), flush=True)
            rows.append(st)

    if not rows:
        sys.exit("Nothing processed.")
    summ = pd.DataFrame(rows).set_index("month")
    a.qa_dir.mkdir(parents=True, exist_ok=True)
    summ.to_csv(a.qa_dir / "monthly_summary.csv")

    L = ["TRADE PANEL QA", "=" * 60,
         f"Months processed: {len(summ)}",
         f"Incomplete months (missing chapters): {int((~summ['complete']).sum())}"
         + ("  -> " + ", ".join(f"{m} (ch {r['missing_chapters']})" for m, r in summ[~summ['complete']].iterrows())
            if (~summ['complete']).any() else ""),
         f"HS10-months failing value reconciliation: {int(summ['hs10_value_mismatch'].sum()):,} "
         f"of {int(summ['n_hs10_checked'].sum()):,}",
         f"HS10-months failing duty reconciliation:  {int(summ['hs10_duty_mismatch'].sum()):,}",
         f"Country value / '-' total value (should be 1.000): "
         f"{summ['value_country'].sum() / summ['value_total_rows'].sum():.4f}",
         f"Duplicate (hs10, country, month) keys: {int(summ['dup_country_keys'].sum()):,}",
         f"Exact duplicate rows dropped: {int(summ['dup_rows_dropped'].sum()):,}",
         f"Rows with HS10 not in concordance map: {int(summ['rows_not_in_map'].sum()):,}",
         f"Negative-value rows: {int(summ['negative_value_rows'].sum()):,}", "",
         "Realized AETR (duty / value, country rows), percent:",
         "  month     world   china"]
    for m, r in summ.iterrows():
        L.append(f"  {m}   {r['aetr_world_pct']:5.2f}   {r['aetr_china_pct']:5.2f}")
    L += ["", "Paper's figures for comparison (Azzimonti & Titcomb 2026):",
          "  world May 2025 = 8.7 ; world Oct 2025 = about 11 ; world Dec 2025 = 9.3 ;",
          f"  China Dec 2025 = {PAPER_CHINA_DEC25} ; China 2024 average = 10.7"]
    text = "\n".join(L)
    (a.qa_dir / "summary.txt").write_text(text + "\n")
    print("\n" + text)


if __name__ == "__main__":
    main()
