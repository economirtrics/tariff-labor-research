# Dynamic Local Labor-Market Effects of the 2025 U.S. Tariffs
**Working title.** Cumulative responses to realized tariff exposure
**Amir Azlan, University of Illinois Urbana-Champaign, 2026 (draft)**

*Positioning:* a continuation of Azzimonti & Titcomb (2026, FRB Richmond WP 26-08, "AT2026"). We keep their data construction and exposure measures and ask whether their "negligible effects" result survives a dynamic, pre-trend-tested, inference-robust specification over a longer window (Jan 2025 - Mar 2026).


> **Status update (November 2026).** The estimating equations in section 4.2-4.3 (cumulated
> distributed lag; local projections) were implemented in `scripts/05`-`07` and set aside:
> the 2025 tariffs are a single synchronized shock, so event-time lag designs are not
> identified (see `scripts/07_diagnostics_and_lp.Rmd`). The main specification is now fixed
> 2025 county exposure interacted with calendar-month indicators, with the unemployment rate
> in levels, county x calendar-month and date fixed effects, 2024 as the reference year and
> 2023 as the placebo year (`scripts/08_event_study_levels.Rmd`). Sections 1-3 and 5-7 of
> this outline still describe the motivation and contribution.

---

## 1. What AT2026 find, and what they leave open

**Found.** Pass-through of realized tariffs into import prices is ~98%; counties more exposed to import protection (IP) saw small relative declines in unemployment; rising input costs (RIC) did not move unemployment but lowered labor-force participation; all effects are economically small.

**Their explanation for small effects (such as it is).** Only a hedge: the contrast with 2018-19 "should be interpreted cautiously" given differences in scope, timing, and composition of trade-partner retaliation. They do not attribute the result to compensation, inventories, or fiscal policy, and they state that retaliatory export tariffs and general-equilibrium channels are not captured.

**Open issues we can address.**
1. *Static spec, no timing.* Eq. (3) regresses 12-month log changes on contemporaneous exposure. It cannot show when effects appear, and cannot formally test pre-trends. Their own Figure 13 (right panel) shows high-exposure counties had *higher* unemployment before implementation, a pre-trend flag.
2. *Overlapping 12-month changes* induce serial correlation within county.
3. *Endogenous exposure.* Realized tariffs embed front-loading, sourcing shifts, and exemption use (the authors acknowledge this).
4. *Shift-share inference.* Exposure varies by ~20 manufacturing industries x county shares; state clustering does not address correlated exposure across counties through shared industry shocks.
5. *IP and RIC move together* (their Figure 12); separate identification rests on small differences.
6. *Short window.* One calendar year of post-period; labor adjustment and inventory drawdown may take longer.
7. *Outcome definition.* Log change of a rate (percent change in the unemployment rate) is awkward for low-unemployment counties; LAUS is model-based and smoothed.

## 2. Economic reasoning

Tariffs reach a county through two channels with opposite signs, weighted by the local industry mix:

| Channel | Mechanism | Predicted effect on unemployment |
|---|---|---|
| Import protection (IP) | Higher import prices shift demand to domestic substitutes; import-competing producers expand | Negative |
| Rising input costs (RIC) | Downstream firms face higher intermediate-input costs, margins compress, output/hours fall | Positive (and lower LFP) |
| Not captured by either | Retaliation on exports, policy uncertainty, consumer-price effects, fiscal offsets | Ambiguous |

**Timing predictions (motivating a dynamic design).**
- Imports front-loaded in early 2025 (AT2026 Fig. 9), so firms held inventory bought at pre-tariff prices. RIC effects on employment should therefore *lag* the tariff change.
- IP effects require capacity expansion and hiring, which also takes time.
- A single-year static regression can miss both. Extending to Q1 2026 gives a better chance to see them.

**Hypotheses.**
- H1: Cumulative IP effect on unemployment is negative and grows with horizon.
- H2: Cumulative RIC effect on unemployment is positive, appearing later than IP.
- H3: No pre-trends: cumulative lead effects are zero.
- H4: Effects are larger in counties with high manufacturing employment shares.

## 3. Data and variables (reused from AT2026)

- **Customs:** Census HS10 x country x month (value, calculated duty, quantity), Jan 2024 - Mar 2026. Realized tariff = duty / value.
- **Industry level:** common level for tariffs, BEA use table and county shares. AT2026 say NAICS-3, but the BEA Summary use table merges some NAICS-3 sectors (311+312, 313+314, 315+316) and splits 336. Proposal: use **BEA Summary industries** as the common level; QCEW aggregates up to it (NAICS-4 needed to split 336).
- **Exposure inputs:** domestic absorption Q + m - x (BEA output, exports; imports from customs), BEA use table for S_ih = u_ih / (iota_i + omega_i).
- **County shares:** QCEW 2024 employment, N_ic / N_c (base year 2024).
- **Outcome:** LAUS county unemployment rate (series measure 03).

## 4. Estimating equations

### 4.1 Exposure (monthly flow version of AT2026's measures)

Realized tariff with fixed 2024 product-country weights:
$$\tau^{r,b}_{i,t}=\sum_{n,\,j\in\Gamma^i}\tau^{r}_{jn,t}\,\frac{m_{jn,24}}{m_{i,24}},\qquad \Delta\tau^{r,b}_{i,t}=\tau^{r,b}_{i,t}-\tau^{r,b}_{i,t-1}$$

Industry exposure (A_i = Q_i + m_i - x_i, 2024 base):
$$\Delta IP_{i,t}=\frac{m_{i,24}\,\Delta\tau^{r,b}_{i,t}}{A_{i,24}},\qquad
\Delta RIC_{i,t}=\sum_h S_{ih}\,\frac{m_{h,24}\,\Delta\tau^{r,b}_{h,t}}{A_{h,24}}$$

County exposure (shift-share, predetermined shares):
$$\Delta Z^{X}_{c,t}=\sum_i \frac{N_{ic,24}}{N_{c,24}}\,\Delta X_{i,t},\qquad X\in\{IP,\,RIC\}$$

The level $Z^X_{c,t}=\sum_{s\le t}\Delta Z^X_{c,s}$ is the cumulative exposure; AT2026's 12-month change is the sum of twelve monthly changes of this object.

### 4.2 Primary: distributed-lag event study with cumulative effects

$$u_{c,t}=\alpha_c+\gamma_t+\sum_{m=-G}^{M}\Big(\beta^{IP}_m\,\Delta Z^{IP}_{c,t-m}+\beta^{RIC}_m\,\Delta Z^{RIC}_{c,t-m}\Big)+\varepsilon_{c,t}$$

($m<0$ are leads.) The cumulative effect at event time $k$ of a permanent unit increase in exposure:
$$\delta^X_k=\begin{cases}0 & k<-G\\ \sum_{m=-G}^{k}\beta^X_m & -G\le k\le M\\ \sum_{m=-G}^{M}\beta^X_m & k>M\end{cases}$$

- Pre-trend test: $H_0:\ \delta^X_k=0$ for $-G\le k\le -1$.
- Standard errors for $\delta_k$ from the linear combination of $\hat\beta_m$.
- *To decide:* endpoint binning (entering the last lag in levels) to preserve sample, following Schmidheiny & Siegloch; to be checked against the paper before coding.

### 4.3 Robustness: local projections

$$u_{c,t+h}-u_{c,t-1}=\alpha_h+\gamma_{t,h}+\delta^{IP}_h\,\Delta Z^{IP}_{c,t}+\delta^{RIC}_h\,\Delta Z^{RIC}_{c,t}+\sum_{l=1}^{L}\big(\phi^{IP}_l\Delta Z^{IP}_{c,t-l}+\phi^{RIC}_l\Delta Z^{RIC}_{c,t-l}+\psi_l\Delta u_{c,t-l}\big)+e_{c,t,h}$$

$h\in[-G,M]$; $h<0$ are placebo leads. In population $\delta_h$ equals $\delta_k$ above; LP is less efficient but more robust to misspecification of the lag structure.

### 4.4 Seasonality

LAUS county series (`LAUCN...`) appear to be *not seasonally adjusted* (verify on BLS series-ID documentation). Time FE absorb national seasonality, not county-specific. Options:
- (a) Outcome = 12-month difference $u_{c,t}-u_{c,t-12}$, as in AT2026 (valid for horizons up to $11-G$ in the DL form);
- (b) Levels with county x calendar-month FE (costly with ~2 years of data).

### 4.5 Inference

- Baseline: cluster by state (as AT2026), plus wild-cluster bootstrap (~50 clusters).
- Shift-share-robust standard errors (Adao-Kolesar-Morales) since identification comes from industry-level tariff variation.
- Report IP/RIC collinearity diagnostics; also IP-only and RIC-only specifications.

### 4.6 Robustness menu

1. Statutory-tariff exposure (predicted), and as an instrument for realized exposure.
2. Trim top 1% of exposure (as AT2026); drop outlier small counties (< 1,000 employees).
3. 2023 base-year shares.
4. Placebo: 2024 "pseudo-shocks"; non-traded industries.
5. Heterogeneity: manufacturing share, farm dependence, USMCA exposure.
6. Translate to magnitudes (percentage points, jobs) and compare to Flaaen & Pierce (2024).

## 5. Why were 2025 effects small? Candidate explanations to test or discuss

| Candidate | Evidence so far | How we could test |
|---|---|---|
| Short window, inventory buffers | AT2026 Fig. 9 shows front-loading | Longer horizons; lagged RIC effects (H2) |
| Less retaliation than 2018-19 | AT2026 raise it; not measured | Add export exposure x_i as a control |
| Government compensation | USDA Farmer Bridge Assistance: ~$12B announced Dec 2025, payments expected by end-Feb 2026; vs ~$23B in 2018-19 | Weak fit: aimed at row-crop farmers, late, and smaller; does not target manufacturing RIC. Possible heterogeneity test in farm-dependent counties, Q1 2026 only |
| Tax policy / investment incentives (OBBBA) | Not verified | Search before using; would be a discussion point only |
| Exemptions / USMCA compliance | AT2026 cite rising compliance | Already inside realized-rate measure |

**Honest read:** the compensation story is a poor fit for the manufacturing exposure measures and should be a footnote or an exploratory heterogeneity check, not the main explanation.

## 6. Proposed paper structure

1. Introduction (motivation, AT2026 as baseline, preview of results)
2. Background: 2025 tariff policy and AT2026's findings
3. Conceptual framework: protection vs cost channels, timing predictions
4. Data and variable construction
5. Empirical strategy (4.1-4.5)
6. Results: (i) pre-trend tests, (ii) cumulative IP/RIC effects, (iii) comparison with AT2026 static estimates
7. Robustness and heterogeneity
8. Discussion: interpreting small effects; compensation and other offsets
9. Conclusion

## 7. Potential contributions to the literature

1. **Dynamics:** first cumulative-effect (event-study) estimates of 2025 tariff exposure on county labor markets, with formal pre-trend tests.
2. **Identification:** realized-vs-statutory exposure comparison and instrumenting realized exposure with statutory exposure.
3. **Inference:** exposure-robust shift-share standard errors for the Flaaen-Pierce county framework.
4. **Measurement:** decomposing the IP/RIC channels when they are highly correlated.
5. **Horizon:** extends the post-period through Q1 2026 (and LAUS outcomes beyond, with caution since tariff exposure is unobserved after Mar 2026).
6. **Reconciliation:** whether the "2025 vs 2018-19" contrast reflects genuinely different tariffs or simply a short window.

## 8. Open decisions

- Industry level: BEA Summary (recommended) vs NAICS-3.
- G and M (candidate: G = 3, M = 9; sample allows roughly 26 monthly changes).
- Seasonality approach (4.4a vs 4.4b).
- 2024 QCEW needed (uploaded file is 2025); BEA table header says 2025, confirm the base year.
- Customs: filter Census country *aggregates* (e.g., total `-`, region codes) before summing.
