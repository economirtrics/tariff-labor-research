# Concordance Strategy: HS10 -> NAICS-3 -> BEA Summary

**Goal.** Put customs tariffs (HS10), BEA input-output data, and QCEW county employment on one industry level so Local IP and Local RIC can be built as in Azzimonti & Titcomb (2026).
**Chain.** HS10 -> NAICS-6 -> NAICS-3 (paper's level) -> BEA Summary group (only where the BEA tables need it).

## 1. Sources

| Need | Source | Status |
|---|---|---|
| HS10 -> NAICS-6 (primary) | Census import concordance files `impconcord23/24/25/26.xlsx` (columns: `commodity` = HS10, `naics` = 6-digit NAICS, `end_use`, `sitc`, `usda`, `hitech`). | **Obtained and checked:** one NAICS-6 per HS10, no duplicates; NAICS assignments stable across vintages (0 changes 2024->2025, 2 changes 2025->2026). Code turnover between vintages is small (a few hundred codes per year). |
| Cross-check / older codes | Pierce & Schott (2012, JESM) HS10 -> NAICS-6 concordance | Standard reference; coverage of 2024-26 HS codes **unconfirmed** |
| NAICS -> BEA Summary | BEA publishes a NAICS-to-I-O crosswalk with the I-O accounts | Locate current file; also hand-check (about 30 manufacturing rows) |
| Country filter | Census Schedule C (country codes) | Needed to drop aggregate `CTY_CODE` rows |

## 2. Algorithm

1. **Collect codes.** Extract every distinct HS10 in `data/raw/trade/chunks` (2024-01 to 2026-03) with its total 2024 import value.
2. **Exact match** on HS10 to the Census concordance. Record `match_level = "hs10"`.
3. **Fallback ladder** for unmatched codes (HS codes are revised during the year, so a 2026 file will miss some 2024 codes): take the import-value-weighted modal NAICS-6 among matched codes sharing the first 8, then 6, then 4 digits. Record `match_level = "hs8" / "hs6" / "hs4"`.
4. **Special chapters.** Chapters 98 and 99 (special provisions) have no industry. Drop them from industry aggregates and report their value share. Chapter 77 is reserved.
5. **NAICS-6 -> NAICS-3** by truncation.
6. **NAICS-3 -> BEA Summary** (1:1 except):
   - 311 + 312 -> `311FT`; 313 + 314 -> `313TT`; 315 + 316 -> `315AL`
   - 336 splits into `3361MV` (NAICS 3361-3363) and `3364OT` (3364-3369); this needs NAICS-4 detail, so keep NAICS-4 through step 5 for chapter 87/88/89 products and QCEW (`agglvl_code` 76).
7. **Handling the BEA mismatch (our decision).** Tariffs and county shares are built at NAICS-3, as in the paper. For BEA inputs (Q, x, use table), merged groups use the group's value, and `3361MV` + `3364OT` are summed for NAICS-336. This deviation will be documented.

## 3. Output and QA

**Output:** `data/processed/hs10_naics_map.csv` with columns `hs10, naics6, naics3, bea_sector, match_level, source`.

**QA checks (report in the README / email):**
- Match rate by HS10 count and by 2024 import value, by chapter and by `match_level`.
- Top 20 unmatched or fallback codes by value.
- **Validation target:** industry average realized tariffs should come close to AT2026 Table 2 (e.g. Apparel NAICS 315: 14.82 in 2024, 24.88 in 2025). Large gaps indicate a concordance or aggregation error.
- Country filter check: sum of country-level rows should reproduce the `-` total row in each chunk.

## 4. Pipeline (Python for data prep, R for estimation and the Rmd)

| Script | Job |
|---|---|
| `01_build_concordance.py` | Steps in section 2 |
| `02_build_trade_panel.py` | Combine chunks, drop aggregate countries, save parquet |
| `03_industry_tariffs.py` | Realized tariffs by industry with fixed 2024 weights; monthly changes |
| `04_qcew_shares.py` | Read 2024 county files (`data/raw/qcew/2024/2024.q1-q4.by_area/`); county x industry employment; own_code, agglvl and suppression handled explicitly |
| `05_bea_io.py` | `data/raw/2024 BEA Table.csv` -> A_i = Q + m - x, S_ih |
| `06_laus.py` | Parse `series_id` (measure `03` = unemployment rate; county FIPS in characters 6-10); drop `M13` (annual average) |
| `tariff_event_study.Rmd` | Estimation (DL event study with county x month FE; 12-month-difference variant as robustness; G = 3, M = 9) and rendered figures |

## 5. Risks to resolve before running

- Confirm the NAICS field and layout in `IMP-CODE.TXT`.
- Confirm that Pierce-Schott or Census files cover HS codes active in 2024-26.
- BEA table year (2024 base, per paper) and where imports m_i come from (customs vs BEA).
- QCEW suppression in small counties understates local exposure; decide how to treat it.

## 6. Repo hygiene before pushing

- Add `data/` and `.env` to `.gitignore`. **Do not commit the API key** (`CENSUS_API_KEY`) or raw data (thousands of files).
- Push `scripts/`, `docs/` (this file and `tariff_paper_outline.md`), and a short README.
