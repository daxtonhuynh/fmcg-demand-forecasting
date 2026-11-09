-- Planning questions answered in SQL. Each block starts with "-- name: <id>" and
-- "-- question: ..."; the pipeline runs every block and saves one CSV per query.
-- Placeholders in braces are filled from the stage outputs (champion, default policy,
-- base cost assumptions) so the SQL and Python answers can be reconciled.

-- name: q1_interval_calibration
-- question: How often does 2025 demand fall below each forecast quantile? (champion forecast, 1 month ahead)
SELECT qmethod, tau,
       avg(CASE WHEN actual_units <= quantile_units THEN 1.0 ELSE 0.0 END) AS achieved_coverage,
       avg(CASE WHEN actual_units <= quantile_units THEN 1.0 ELSE 0.0 END) - tau AS calibration_gap,
       count(*) AS forecasts
FROM fact_quantile_forecast q
JOIN dim_month m ON m.month_key = q.origin_month_key
WHERE m.is_test AND q.method = '{champion_method}' AND q.window_months = 1
GROUP BY qmethod, tau
ORDER BY qmethod, tau;

-- name: q2_calibration_monitor
-- question: Would a running coverage check have flagged an interval method during 2025? (95% quantile)
WITH hits AS (
    SELECT qmethod, m.month,
           sum(CASE WHEN actual_units <= quantile_units THEN 1 ELSE 0 END) AS hits,
           count(*) AS n
    FROM fact_quantile_forecast q
    JOIN dim_month m ON m.month_key = q.origin_month_key
    WHERE m.is_test AND q.method = '{champion_method}' AND q.window_months = 1 AND q.tau = 0.95
    GROUP BY qmethod, m.month
)
SELECT qmethod, month,
       sum(hits) OVER w AS cumulative_hits,
       sum(n) OVER w AS cumulative_forecasts,
       sum(hits) OVER w / sum(n) OVER w AS cumulative_coverage
FROM hits
WINDOW w AS (PARTITION BY qmethod ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
ORDER BY qmethod, month;

-- name: q3_hierarchy_accuracy
-- question: How accurate is each reconciliation approach at every level, and do the numbers add up?
SELECT base_set, approach, level,
       sum(abs(actual_units - forecast_units)) / sum(actual_units) AS wape,
       sum(forecast_units - actual_units) / sum(actual_units) AS bias,
       rank() OVER (PARTITION BY base_set, level
                    ORDER BY round(sum(abs(actual_units - forecast_units)) / sum(actual_units), 10)) AS rank_in_level
FROM fact_reconciled_forecast
GROUP BY base_set, approach, level
ORDER BY base_set, level, rank_in_level, approach;

-- name: q4_policy_frontier
-- question: What does each service target cost in stock and lost profit? (lead time {base_lead}, champion forecast)
WITH per_sku AS (
    SELECT s.policy_id, s.sku_key,
           sum(s.demand) AS demand, sum(s.sales) AS sales, sum(s.lost) AS lost,
           sum(CASE WHEN s.lost > 1e-9 THEN 1 ELSE 0 END) AS stockout_months, count(*) AS months,
           avg((s.opening + s.receipts + s.closing) / 2) AS avg_on_hand
    FROM fact_inventory_sim s
    WHERE s.is_test
    GROUP BY s.policy_id, s.sku_key
)
SELECT p.policy_id, p.family, p.qmethod, p.target_label, p.target_value, p.cover_months,
       sum(x.sales) / sum(x.demand) AS fill_rate,
       1 - sum(x.stockout_months) / sum(x.months) AS cycle_service_level,
       sum(x.avg_on_hand * k.unit_cost) AS avg_inventory_value,
       sum(x.avg_on_hand * k.unit_cost * {holding_rate} / 12 * x.months) AS holding_cost,
       sum(x.lost * greatest(k.{lost_col}, 0)) AS lost_value,
       sum(x.avg_on_hand * k.unit_cost * {holding_rate} / 12 * x.months) + sum(x.lost * greatest(k.{lost_col}, 0)) AS total_cost
FROM per_sku x
JOIN dim_policy p USING (policy_id)
JOIN dim_sku k USING (sku_key)
WHERE p.lead_time = {base_lead} AND p.method = '{champion_method}'
GROUP BY ALL
ORDER BY total_cost;

-- name: q5_default_policy_by_segment
-- question: Under the default policy, where is the stock and where are the stock-outs? (ABC class x category)
WITH per_sku AS (
    SELECT sku_key, sum(demand) AS demand, sum(sales) AS sales,
           sum(CASE WHEN lost > 1e-9 THEN 1 ELSE 0 END) AS stockout_months,
           avg((opening + receipts + closing) / 2) AS avg_on_hand
    FROM fact_inventory_sim
    WHERE is_test AND policy_id = '{default_policy}'
    GROUP BY sku_key
)
SELECT k.abc_class, k.category, count(*) AS skus,
       round(avg(k.critical_ratio_base), 3) AS avg_service_target,
       sum(x.sales) / sum(x.demand) AS fill_rate,
       sum(x.stockout_months) AS stockout_months,
       sum(x.avg_on_hand * k.unit_cost) AS avg_inventory_value,
       sum(x.avg_on_hand * k.unit_cost) / sum(x.demand * k.unit_cost / 12) AS months_of_cover
FROM per_sku x JOIN dim_sku k USING (sku_key)
GROUP BY ROLLUP (k.abc_class, k.category)
ORDER BY k.abc_class NULLS LAST, k.category NULLS LAST;

-- name: q6_monthly_inventory_trend
-- question: How do stock, receipts and lost sales move month by month under the default policy?
SELECT m.month,
       sum((s.opening + s.receipts + s.closing) / 2 * k.unit_cost) AS avg_inventory_value,
       sum(s.receipts * k.unit_cost) AS receipts_value,
       sum(s.lost) AS lost_units,
       sum(CASE WHEN s.lost > 1e-9 THEN 1 ELSE 0 END) AS skus_with_stockout,
       sum(sum(s.lost)) OVER (ORDER BY m.month) AS cumulative_lost_units
FROM fact_inventory_sim s
JOIN dim_month m USING (month_key)
JOIN dim_sku k USING (sku_key)
WHERE s.policy_id = '{default_policy}' AND s.is_test
GROUP BY m.month
ORDER BY m.month;

-- name: q7_replenishment_plan
-- question: What should be ordered for the first planning month after the data ends?
SELECT k.sku, k.product_name, k.category, k.abc_class,
       r.plan_month, r.arrival_month, round(r.service_target, 3) AS service_target,
       round(r.expected_demand_protection) AS expected_demand, round(r.safety_stock) AS safety_stock,
       round(r.order_up_to) AS order_up_to, round(r.inventory_position) AS inventory_position,
       round(r.recommended_order) AS recommended_order, round(r.order_value_at_cost, 2) AS order_value_at_cost,
       sum(r.order_value_at_cost) OVER (ORDER BY r.order_value_at_cost DESC) /
           sum(r.order_value_at_cost) OVER () AS cumulative_share_of_order_value
FROM fact_replenishment_plan r
JOIN dim_sku k USING (sku_key)
WHERE r.policy_id = '{default_policy}'
ORDER BY r.order_value_at_cost DESC;

-- name: q8_value_of_information
-- question: How much stock and cost does seeing large orders in advance save?
WITH agg AS (
    SELECT policy, visibility, avg(sku_wape) AS sku_wape, avg(avg_inventory_value) AS inventory_value,
           avg(fill_rate) AS fill_rate, avg(total_cost) AS total_cost, count(*) AS runs
    FROM fact_voi_run GROUP BY policy, visibility
)
SELECT *,
       1 - inventory_value / first_value(inventory_value) OVER w AS inventory_reduction,
       first_value(total_cost) OVER w - total_cost AS cost_saving
FROM agg
WINDOW w AS (PARTITION BY policy ORDER BY visibility)
ORDER BY policy, visibility;

-- name: q9_forecast_value_added
-- question: Which planner overrides improve on the statistical forecast? (one random draw per archetype)
SELECT archetype,
       sum(abs(actual_units - statistical_forecast)) / sum(actual_units) AS wape_statistical,
       sum(abs(actual_units - final_forecast)) / sum(actual_units) AS wape_final,
       100 * (sum(abs(actual_units - statistical_forecast)) - sum(abs(actual_units - final_forecast))) / sum(actual_units) AS fva_points,
       avg(CASE WHEN overridden THEN 1.0 ELSE 0.0 END) AS override_share,
       avg(CASE WHEN overridden THEN (abs(actual_units - final_forecast) < abs(actual_units - statistical_forecast))::INT END) AS overrides_improved_share,
       sum(final_forecast - actual_units) / sum(actual_units) AS bias_final
FROM fact_override_log
GROUP BY archetype
ORDER BY fva_points DESC;
