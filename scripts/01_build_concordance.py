#!/usr/bin/env python3
"""
01_build_concordance.py
=======================
Build the HS10 -> NAICS-6 -> NAICS-3 -> BEA Summary concordance used to turn
customs tariffs (HS10) into industry-level tariff exposure.

Inputs
------
data/raw/concordance/impconcord{23,24,25,26}.csv   Census import concordance
    (columns used: commodity = HS10, naics = NAICS-6, end_use)
data/raw/trade/chunks/trade_YYYY_MM_CH.csv          Census API chunks
    (only the all-country total rows, CTY_CODE == "-", are read here)

Outputs
-------
data/processed/hs10_naics_map.csv                   the concordance
output/concordance_qa/summary.txt                   match-rate report
output/concordance_qa/non_exact_top.csv             largest non-exact matches

Method
------
1. Stack the concordance vintages newest-first and keep one row per HS10
   (NAICS assignments are nearly identical across vintages).
2. Exact-match every HS10 that appears in the trade chunks.
3. Unmatched codes fall back to the import-value-weighted modal NAICS-6 among
   concordance codes sharing the first 8, then 6, then 4 digits.
4. NAICS-6 -> NAICS-3 by truncation; NAICS -> BEA Summary via explicit rules
   (311+312, 313+314, 315+316 merge; 336 splits using NAICS-4).
5. Chapters 98/99 (special provisions) are flagged and excluded from industry
   aggregates.

Usage
-----
    python3 scripts/01_build_concordance.py
    python3 scripts/01_build_concordance.py --years 2024 2025 2026
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------------
# NAICS -> BEA Summary rules
# ----------------------------------------------------------------------------
# Industries in Azzimonti & Titcomb (2026), Table 2 (NAICS-3).
PAPER_NAICS3 = {
    "111", "112", "113", "114", "115", "211", "212",
    "311", "312", "313", "314", "315", "316", "321", "322", "323", "324",
    "325", "326", "327", "331", "332", "333", "334", "335", "336", "337", "339",
}

BEA_ONE_TO_ONE = {
    "211", "212", "213", "321", "322", "323", "324", "325", "326", "327",
    "331", "332", "333", "334", "335", "337", "339",
}


def naics_to_bea(naics6: str) -> str:
    """Map a NAICS-6 code to a BEA Summary industry code (see strategy doc)."""
    if not isinstance(naics6, str) or len(naics6) < 3:
        return "UNMAPPED"
    n3, n4 = naics6[:3], naics6[:4]
    if naics6[0] == "9":  # Census placeholder codes (910/920/930/980/990), not industries
        return "NONINDUSTRY"
    if n3 == "336":
        return "3361MV" if n4 in {"3361", "3362", "3363"} else "3364OT"
    if n3 in {"111", "112"}:
        return "111CA"
    if n3 in {"113", "114", "115"}:
        return "113FF"
    if n3 in {"311", "312"}:
        return "311FT"
    if n3 in {"313", "314"}:
        return "313TT"
    if n3 in {"315", "316"}:
        return "315AL"
    if n3 in BEA_ONE_TO_ONE:
        return n3
    if naics6[:2] == "22":
        return "22"
    return "UNMAPPED"


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------
def read_csv_robust(path: Path, **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin1"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode {path}")


def load_concordance(conc_dir: Path, vintages) -> pd.DataFrame:
    """Stack concordance vintages newest-first; one row per HS10."""
    frames = []
    for yy in sorted(vintages, reverse=True):
        path = conc_dir / f"impconcord{yy}.csv"
        if not path.exists():
            sys.exit(f"Missing concordance file: {path}")
        df = read_csv_robust(path, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        need = {"commodity", "naics"}
        if not need <= set(df.columns):
            sys.exit(f"{path.name}: expected columns {need}, found {list(df.columns)}")
        if "end_use" not in df.columns:
            df["end_use"] = pd.NA
        df = df[["commodity", "naics", "end_use"]].copy()
        df["commodity"] = df["commodity"].str.strip().str.zfill(10)
        df["naics"] = df["naics"].str.strip()
        df["vintage"] = 2000 + int(yy)
        frames.append(df)
    master = pd.concat(frames, ignore_index=True)
    master = master.dropna(subset=["commodity", "naics"])
    master = master.drop_duplicates("commodity", keep="first")  # newest wins
    return master.rename(columns={"commodity": "hs10", "naics": "naics6"})


def scan_trade(chunk_dir: Path, years) -> pd.DataFrame:
    """Total import value by (year, HS10) from the all-country rows ('-')."""
    parts, n_files, n_bad, n_no_total = [], 0, 0, 0
    for yr in years:
        for f in sorted(chunk_dir.glob(f"trade_{yr}_*.csv")):
            n_files += 1
            try:
                d = pd.read_csv(
                    f,
                    usecols=["I_COMMODITY", "CTY_CODE", "GEN_VAL_MO"],
                    dtype={"I_COMMODITY": str, "CTY_CODE": str},
                )
            except Exception:
                n_bad += 1
                continue
            if d.empty:
                continue
            tot = d[d["CTY_CODE"] == "-"]
            if tot.empty:
                n_no_total += 1
                continue
            tot = tot.assign(
                year=yr,
                hs10=tot["I_COMMODITY"].str.strip().str.zfill(10),
                value=pd.to_numeric(tot["GEN_VAL_MO"], errors="coerce").fillna(0.0),
            )
            parts.append(tot[["year", "hs10", "value"]])
    print(f"Scanned {n_files:,} chunk files "
          f"({n_bad} unreadable, {n_no_total} with no '-' total rows)")
    if not parts:
        sys.exit("No trade data found. Check --chunk-dir and --years.")
    out = pd.concat(parts, ignore_index=True)
    return out.groupby(["year", "hs10"], as_index=False)["value"].sum()


# ----------------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------------
def build_modal_maps(master: pd.DataFrame, weight: pd.Series, levels=(8, 6, 4)):
    """For each prefix length, prefix -> value-weighted modal NAICS-6."""
    w = master.assign(w=master["hs10"].map(weight).fillna(0.0) + 1.0)  # +1 = count tiebreak
    maps = {}
    for k in levels:
        g = (w.assign(pref=w["hs10"].str[:k])
               .groupby(["pref", "naics6"], as_index=False)["w"].sum()
               .sort_values(["pref", "w"], ascending=[True, False])
               .drop_duplicates("pref"))
        maps[k] = dict(zip(g["pref"], g["naics6"]))
    return maps


def build_map(master: pd.DataFrame, trade: pd.DataFrame) -> pd.DataFrame:
    value_total = trade.groupby("hs10")["value"].sum()
    master = master.copy()
    master["match_level"] = "hs10"

    trade_codes = pd.Index(value_total.index)
    missing = trade_codes.difference(pd.Index(master["hs10"]))
    modal = build_modal_maps(master, value_total)

    rows = []
    for code in missing:
        for k in (8, 6, 4):
            naics = modal[k].get(code[:k])
            if naics is not None:
                rows.append((code, naics, pd.NA, f"hs{k}", pd.NA))
                break
        else:
            rows.append((code, pd.NA, pd.NA, "none", pd.NA))
    fb = pd.DataFrame(rows, columns=["hs10", "naics6", "end_use", "match_level", "vintage"])

    out = pd.concat([master, fb], ignore_index=True)
    out["naics3"] = out["naics6"].str[:3]
    out["naics4"] = out["naics6"].str[:4]
    out["bea_sector"] = out["naics6"].map(naics_to_bea)
    out["special_chapter"] = out["hs10"].str[:2].isin(["98", "99"])
    out["in_paper_sample"] = out["naics3"].isin(PAPER_NAICS3)
    out["non_industry_code"] = out["naics6"].str[:1].eq("9").fillna(False).astype(bool)
    out["use_in_industry_agg"] = (
        (~out["special_chapter"]) & (~out["non_industry_code"]) & out["naics6"].notna()
    )
    out["import_value_total"] = out["hs10"].map(value_total).fillna(0.0)
    cols = ["hs10", "naics6", "naics4", "naics3", "bea_sector", "end_use",
            "match_level", "vintage", "special_chapter", "non_industry_code", "in_paper_sample",
            "use_in_industry_agg", "import_value_total"]
    return out[cols].sort_values("hs10").reset_index(drop=True)


# ----------------------------------------------------------------------------
# QA
# ----------------------------------------------------------------------------
def qa_report(cmap: pd.DataFrame, trade: pd.DataFrame, qa_dir: Path) -> str:
    qa_dir.mkdir(parents=True, exist_ok=True)
    t = trade.merge(cmap, on="hs10", how="left")
    for col in ("special_chapter", "non_industry_code", "in_paper_sample", "use_in_industry_agg"):
        t[col] = t[col].fillna(False).astype(bool)
    t["match_level"] = t["match_level"].fillna("none")
    t["bea_sector"] = t["bea_sector"].fillna("UNMAPPED")
    lines = []
    tot = t["value"].sum()

    def share(mask):
        return t.loc[mask, "value"].sum() / tot if tot else float("nan")

    lines.append("CONCORDANCE QA")
    lines.append("=" * 60)
    lines.append(f"Distinct HS10 codes in trade data: {trade['hs10'].nunique():,}")
    lines.append(f"Concordance rows written: {len(cmap):,}")
    lines.append("")
    lines.append("Match level (share of import value / count of trade HS10):")
    for lvl in ["hs10", "hs8", "hs6", "hs4", "none"]:
        m = t["match_level"] == lvl
        lines.append(f"  {lvl:5s} value share {share(m):7.3%}   "
                     f"HS10 count {t.loc[m, 'hs10'].nunique():,}")
    lines.append("")
    lines.append("Exact-match value share by year:")
    for yr, g in t.groupby("year"):
        s = g.loc[g["match_level"] == "hs10", "value"].sum() / g["value"].sum()
        lines.append(f"  {yr}: {s:7.3%}")
    lines.append("")
    lines.append(f"Special chapters 98/99 value share: {share(t['special_chapter']):7.3%}")
    lines.append(f"Non-industry NAICS codes (9xx) share: {share(t['non_industry_code']):7.3%}"
                 "  (placeholder codes such as 910/930/980/990)")
    lines.append(f"BEA 'UNMAPPED' value share:        {share(t['bea_sector'] == 'UNMAPPED'):7.3%}")
    lines.append(f"Outside paper's 28 NAICS-3 sample: "
                 f"{share(~t['in_paper_sample'] & t['use_in_industry_agg']):7.3%}")
    lines.append("")
    t["ch"] = t["hs10"].str[:2]
    chap_val = t.groupby("ch")["value"].sum()
    chap_ne = t[t["match_level"] != "hs10"].groupby("ch")["value"].sum()
    chap = pd.DataFrame({"value": chap_val, "non_exact": chap_ne}).fillna(0.0)
    chap["share"] = chap["non_exact"] / chap["value"].where(chap["value"] > 0)
    chap = chap.sort_values("share", ascending=False)
    lines.append("Chapters with the highest non-exact value share (top 10):")
    for ch, r in chap.head(10).iterrows():
        lines.append(f"  ch {ch}: {r['share']:7.3%} of ${r['value']:,.0f}")

    non_exact = (cmap[(cmap["match_level"] != "hs10") & (cmap["import_value_total"] > 0)]
                 .sort_values("import_value_total", ascending=False).head(50))
    non_exact.to_csv(qa_dir / "non_exact_top.csv", index=False)

    text = "\n".join(lines)
    (qa_dir / "summary.txt").write_text(text + "\n")
    return text


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conc-dir", type=Path, default=ROOT / "data/raw/concordance")
    ap.add_argument("--chunk-dir", type=Path, default=ROOT / "data/raw/trade/chunks")
    ap.add_argument("--years", type=int, nargs="+", default=[2023, 2024, 2025, 2026])
    ap.add_argument("--vintages", type=int, nargs="+", default=[23, 24, 25, 26],
                    help="two-digit concordance years, e.g. 23 24 25 26")
    ap.add_argument("--out", type=Path, default=ROOT / "data/processed/hs10_naics_map.csv")
    ap.add_argument("--qa-dir", type=Path, default=ROOT / "output/concordance_qa")
    a = ap.parse_args()

    master = load_concordance(a.conc_dir, a.vintages)
    print(f"Concordance: {len(master):,} unique HS10 codes "
          f"from vintages {sorted(set(master['vintage']))}")

    trade = scan_trade(a.chunk_dir, a.years)
    cmap = build_map(master, trade)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    cmap.to_csv(a.out, index=False)
    print(f"Wrote {a.out} ({len(cmap):,} rows)\n")
    print(qa_report(cmap, trade, a.qa_dir))


if __name__ == "__main__":
    main()
