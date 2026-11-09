# Methodology

This extension starts where the main project stopped. The main project showed that,
on this dataset, no model beats each SKU's historical average (28.2% WAPE one month
ahead, against a noise floor of about 26%). Commercial drivers add nothing once
leakage is removed. So the planning question changes from *"how do we forecast
better?"* to *"how do we plan well around an error we cannot remove, and what would
remove it?"*

Every design choice below follows two rules from the main project:

1. **Only information available at the decision time is used.** Forecasts, interval
   calibration and order decisions at month *t* use data up to month *t − 1*.
2. **Choices are made before looking at the test year.** Champions are picked on
   Jul–Dec 2024; 2025 is touched only for evaluation.

## Time design

| Period | Use |
|---|---|
| Jan 2023 – Dec 2023 | History only |
| Jan 2024 – Jun 2024 | First forecast errors (calibration starts Jan 2024) |
| Jul 2024 – Dec 2024 | Selection period: pick champions; inventory warm-up |
| Jan 2025 – Dec 2025 | Test year: every reported result |
| Jan 2026 | First planning month after the data: replenishment plan |

An *origin* is the first month being forecast. A *window* is the number of months
summed: an order placed now must cover the lead time plus one review month, so with a
1-month lead time the relevant forecast is demand over the next 2 months.

## P2 — Probabilistic forecasts

Point forecasts: historical average, seasonal naive, naive and 3-month moving average
(the main project showed nothing more complex helps). The historical average is
re-confirmed as champion on the selection period (28.0% WAPE vs 32.5–38.1%).

Each point forecast is turned into quantiles from its own past errors. For target
origin *t*, the calibration set is every earlier origin whose whole window had been
observed before *t*. Errors are relative, `e = (actual − forecast) / forecast`, pooled
across SKUs (a single SKU has too few errors).

- **Normal:** `q = F · (1 + z_τ · sd(e))`. The textbook safety-stock formula.
- **Empirical (split-conformal):** the `ceil((n + 1)τ)`-th smallest pooled error.
  Distribution-free, with a finite-sample coverage guarantee if errors are exchangeable.
- **Empirical, scaled:** errors divided by each SKU's coefficient of variation before
  pooling and multiplied back, so volatile SKUs get wider ranges.

Evaluation: coverage of each quantile (share of actuals below it), interval width,
and pinball loss averaged over τ ∈ {0.05, …, 0.99}. The champion is the method with
the lowest pinball loss on the selection period, averaged over windows of 1–3 months.

A **calibration monitor** tracks cumulative coverage of the 95% quantile through the
test year and raises an alarm when the number of hits falls below the 5% one-sided
binomial limit. This is the "continuous evaluation" step of a planning process: it
detects under-covering ranges from live results, without waiting for a re-study.
(It assumes errors are independent across SKUs within a month, which holds in this
data; correlated real-world errors would need a wider limit.)

## P3 — Hierarchical reconciliation

Series: total (1), categories (5), brands (17), SKUs (30). The summing matrix *S*
maps SKUs to every level. Base forecasts per level come from three sets: the
historical average everywhere, seasonal naive everywhere, and the best method per
level on the selection period (seasonal naive for total and category, historical
average for brand and SKU).

Reconciliation methods: bottom-up, top-down with historical proportions, and the
linear projections `ỹ = S (S′W⁻¹S)⁻¹ S′W⁻¹ ŷ` with `W = I` (OLS), `W = diag(S·1)`
(WLS structural) and `W` = shrinkage estimate of the one-step residual covariance
(MinT, Schäfer–Strimmer shrinkage, Wickramasuriya et al. 2019). The planning default
is the set + method with the lowest mean WAPE across the four levels on the
selection period.

One structural point: the historical average is linear, so SKU averages already sum
to the category and total averages. With it, every reconciliation method returns the
same numbers. Reconciliation only matters when levels use different methods.

## P4 — Inventory policy simulation

Policy: periodic review, order-up-to, lost sales. Each month:

1. receive orders due;
2. inventory position = on hand + in transit;
3. order `max(0, S_t − position)`, arriving after the lead time;
4. demand arrives; unmet demand is lost; stock carries over.

`S_t` is the τ-quantile of demand over the protection period (lead time + 1 month).
Policy families:

- **Uniform target:** the same τ ∈ {50, 80, 85, 90, 95, 97, 98, 99%} for every SKU.
- **Cost-optimal per SKU:** τ_i = critical ratio `u_i / (u_i + o_i)`, where `u_i` is the
  cost of a lost unit and `o_i` is one month of holding cost. It is set from unit
  economics before the test year, not tuned on 2025.
- **Rule of thumb:** expected demand + *k* months of forecast as buffer, *k* ∈ {0.25, 0.5, 0.75, 1}.

4 forecast methods × 3 interval methods × 14 targets + 4 × 4 cover rules, for 3 lead
times = 552 policies. Simulation runs Jul 2024 – Dec 2025; only 2025 is scored.
Quantities (units on hand, sold, lost, stock-out months, orders) are stored once and
priced afterwards under each holding rate and lost-sale basis, so the sensitivity
analysis uses identical simulated behaviour.

Metrics: fill rate (share of demand served), cycle service level (share of SKU-months
without a stock-out), average inventory value at cost, holding cost, lost-sale cost,
total cost. The "best uniform target" and "best rule of thumb" in the sensitivity
table are chosen in hindsight on 2025, so they are an upper bound for those rules;
the cost-optimal policy gets no such advantage.

**Decision-based model comparison.** The same cost-optimal policy is run on every
forecast and interval method, so methods are ranked by the money they cost, not only
by WAPE.

## P5 — Value of information and Forecast Value Added

**Value of information.** Orders of ≥ 515 units (the pre-2025 90th percentile) make up
10% of orders, 33% of units, and are 97% B2B. A pipeline forecaster sees each such
order with probability *p*, independently, for the whole protection period:

    forecast = expected base demand + visible large orders + (1 − p) · expected large demand

The intervals are re-calibrated on each scenario's own errors and the cost-optimal
policy is re-run. *p* ∈ {0, 0.25, 0.5, 0.75, 1}, 30 random draws for partial
visibility. Because visible orders are assumed certain and on time, results are an
upper bound on what a real pipeline (with win probabilities and slippage) delivers.

**Forecast Value Added (FVA).** Four simulated planners override the statistical
forecast:

| Archetype | Behaviour |
|---|---|
| Informed | Sees 50% of large orders and adjusts for them (the pipeline forecaster) |
| Optimistic | Adds 20% on a random 30% of SKU-months ("expected campaign lift") |
| Chaser | Averages the statistical forecast with last month's actual |
| Sandbagger | Cuts every forecast by 10% |

FVA = WAPE(statistical) − WAPE(after override), in points. Each override is also run
through the inventory policy, keeping the system's safety stock (planners change the
number, not the buffer), and priced. The override log stores the statistical number,
the final number, a reason code and the actual: the data a real FVA process needs.

## P6 — Warehouse and reconciliation

A separate DuckDB database (`data/warehouse/planning.duckdb`) holds 3 dimensions and
7 facts. 17 data-quality checks cover completeness, key integrity, inventory
identities (balance, continuity, sales ≤ demand) and reconciliation with the raw file;
the pipeline stops if any fails. Nine SQL queries answer the planning questions, and
320 SQL figures are recomputed and matched against the Python results.

## What this design cannot show

- **Real stock-out behaviour.** Demand is assumed uncensored and lost sales do not
  feed back into future demand.
- **Real planner value.** FVA is demonstrated with simulated planners; measuring it
  needs real overrides logged over time.
- **Real pipeline value.** The value-of-information curve is an upper bound under
  certainty; a pipeline with win probabilities would sit below it.
- **Generality.** The dataset shows signs of being synthetic (independent month-to-
  month demand, very even order counts), which makes simple methods hard to beat and
  Normal assumptions nearly right. Real data would reward the empirical intervals and
  the calibration monitor more.
