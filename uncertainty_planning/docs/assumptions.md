# Assumptions

The dataset records orders, prices and costs. It has no inventory, lead times,
stock-outs, planned commercial inputs, customer IDs or planner forecasts. Everything
below fills those gaps. Each assumption is either taken from the data, varied in the
sensitivity analysis, or stated as a limitation.

| Assumption | Value used | Where it comes from | How it is tested |
|---|---|---|---|
| Demand = units sold | Recorded orders are treated as true demand | No stock-out data exists, so sales cannot be uncensored | Limitation (real data needs stock-out flags) |
| Planning grain | SKU × month, one central stock point | 30 SKUs × 36 months, no empty months; finer grains are sparse (SKU × country: 40% empty months) | Fixed |
| Review period | 1 month | Monthly forecasting grain | Fixed |
| Lead time | 1 month | Assumed | 0, 1 and 2 months |
| Unmet demand | Lost (no backorders) | Typical for FMCG retail and distributor supply | Limitation |
| Unit cost | Median COGS per unit of the SKU | Data | — |
| Holding cost | 25% of unit cost per year | Assumed (common planning rule of thumb) | 15%, 25%, 35% |
| Cost of a lost unit | Median profit per unit (after COGS, logistics and marketing) | Data; marketing is booked per order, so it disappears with the order | Also tested with gross margin (price − COGS) |
| Cost-optimal service level | Critical ratio = lost-unit cost / (lost-unit cost + one month of holding) | Newsvendor logic for a stock that carries over | Recomputed for every holding / lost-sale combination |
| Starting stock | Order-up-to level in Jul 2024, nothing in transit | Arbitrary; removed by a 6-month warm-up | Only 2025 is scored |
| Large order | ≥ 515 units (pre-2025 90th percentile of order size) | Data before the test year | — |
| Pipeline visibility | Each large order visible with probability *p*, for the whole protection period, certain and on time | Assumed | *p* = 0, 25, 50, 75, 100%; 30 random draws; reported as an upper bound |
| Planner behaviour | Four archetypes (informed, optimistic, chaser, sandbagger) | Assumed, modelled on documented forecast-bias patterns | 30 random draws where random |
| Ordering cost, capacity, minimum order quantities | Not modelled | — | Limitation |

## What the assumptions do not change

- **Which forecast is best for stock.** The historical average gives the lowest total
  cost in every one of the 18 lead-time × holding × lost-sale combinations, with each
  of the three interval methods (54 of 54 comparisons).
- **Whether cost-optimal per-SKU targets beat a uniform 95% target.** They do in all 18
  combinations (saving 0.5% to 19.8% of holding + lost-sale cost).
- **The direction of the value of information** (tested at the base assumptions). More
  pipeline visibility lowers error, stock and cost at every step.

## What they do change

- **The best uniform service level.** Chosen in hindsight it ranges from 85% to 99%
  across the 18 combinations. There is no single right number, which is why the
  default policy sets the target per SKU from its own economics.
- **Which interval method is cheapest.** Normal ranges win with a 1- or 2-month lead
  time, empirical ranges with no lead time: the cheapest method is the one best
  calibrated over the protection period that the lead time sets.
- **The size of every dollar figure.** Holding and lost-sale costs scale directly with
  the assumed rates; read money figures as orders of magnitude for this dataset.
