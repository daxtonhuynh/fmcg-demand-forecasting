# Decision memo: planning around forecast uncertainty

**To:** Demand planning, supply chain and commercial leads
**Basis:** month-by-month replay of 2025 demand for 30 SKUs (simulation; assumptions in
[`assumptions.md`](assumptions.md))
**Base case:** 1-month lead time, holding cost 25% of unit cost per year, a lost sale costs
its profit

## The situation

SKU demand cannot be forecast better from history: every model tried in the main project
lands at 28–32% error one month ahead, against a noise floor of about 26%. The company
total is far steadier (about 7% error) because SKU noise cancels out when 30 SKUs are summed.
The planning task is therefore to **hold the right buffer against an error that will not go
away, and to find information that does reduce it.**

Under the recommended policy the business holds about **$334K of stock at cost (1.3 months
of demand)**, serves **98.6% of demand**, and carries about **$100K a year** of holding and
lost-sale cost.

## Recommendations

| # | Recommendation | Evidence (2025 simulation) | Estimated impact |
|---|---|---|---|
| 1 | **Keep the historical-average forecast, and rank forecasts by what they cost.** | Cheapest in 54 of 54 lead-time × cost × interval combinations. Naive (39.6% WAPE) costs 28% more than seasonal naive (40.7% WAPE): similar error, very different stock. | Avoids $18K–$72K a year that the next-best methods would add |
| 2 | **Set the service target per SKU from its margin and holding cost** instead of one company-wide level. | Beats a uniform 95% target in 18 of 18 assumption sets. Targets range from 79% (Sparkling Water Berry, thin profit) to 97% (Toothpaste Mint). The best uniform level, even chosen in hindsight, swings from 85% to 99% with the assumptions. | −$5.0K a year (−4.7%) and −$20K of stock vs uniform 95% |
| 3 | **Check monthly that the forecast ranges deliver what they promise**, and switch method when they do not. | Normal ranges promised 95% but covered 92.8% of SKU-months; the monitor flagged them in May 2025. Empirical ranges covered 96.1%. | Keeps the promised service level honest; the method to use depends on the lead time |
| 4 | **Build visibility of large B2B orders into planning** (CRM pipeline, distributor order calendars). | Orders of 515+ units are 10% of orders, 33% of units, 97% B2B. Seeing half of them early: error 28.2% → 23.9%. Seeing all: 18.9%, below the history-only floor. | 50% visible: −$28K stock, −$9.9K a year. 100%: −$67K stock (−20%), −$22K a year (upper bound) |
| 5 | **Log every override with a reason; judge it by cost as well as accuracy; re-size buffers when new information enters.** | Informed overrides: +4.1 WAPE points and −$7.2K a year, but stock unchanged because the buffer was not re-sized (re-sized: −$9.9K and −$28K stock). Optimistic and trend-chasing overrides destroy value (−1.5 and −3.5 points; +$3.4K and +$7.0K a year). Sandbagging loses accuracy (−0.6 points) yet costs slightly less: accuracy alone misjudges it. | Avoid value-destroying overrides; capture the full value of good ones |
| 6 | **Publish one number set that adds up from SKU to company.** | The historical average adds up by construction. Using seasonal naive for the total and splitting it down by historical shares gives 6.6% error at the total with 28.3% at SKU level. | One forecast for Finance and Supply Chain, no reconciliation meetings |

## First action: January 2026 replenishment

The system's plan for the first month after the data: **order about 125K units, $291K at
cost**, arriving in February 2026. Laundry Detergent, Trail Mix Original and Green Tea Bags
are the three largest orders by value. The full list is query `q7_replenishment_plan` and the
dashboard's *Inventory policy* page.

## KPIs to track

| KPI | Current (2025 simulation) | Watch for |
|---|---|---|
| Coverage of the 95% forecast quantile | 92.8% (Normal) · 96.1% (empirical) | Falling below the monitor's alarm limit |
| Fill rate | 98.6% | Drop below the SKU targets' expected level |
| Stock in months of demand | 1.34 | Creep upward without a service gain |
| Forecast Value Added by reason code | Simulated only | Reason codes with negative FVA |
| Share of large-order volume visible in the pipeline | 0% today | Each 25 points ≈ 2–3 WAPE points and ~$5K a year |

## Caveats

These are simulation results on a dataset with signs of being synthetic. Dollar figures
scale with the assumed holding rate and lead time; the rankings and directions held across
all 18 assumption sets tested. The value of information assumes visible orders are certain
and on time, so real gains will be smaller.
