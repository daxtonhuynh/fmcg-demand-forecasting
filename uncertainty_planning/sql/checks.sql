-- Data-quality checks for the planning warehouse.
-- Each check returns one row: check_name, failed_rows (0 = pass). The pipeline
-- stops if any check fails. {raw_csv} is filled in by the pipeline (read-only).

WITH
raw AS (SELECT sum(Units_Sold) AS units FROM read_csv_auto('{raw_csv}')),
q_lag AS (
    SELECT quantile_units,
           lag(quantile_units) OVER (PARTITION BY sku_key, origin_month_key, window_months, method, qmethod
                                     ORDER BY tau) AS prev_q
    FROM fact_quantile_forecast
),
inv_lag AS (
    SELECT opening, lag(closing) OVER (PARTITION BY policy_id, sku_key ORDER BY month_key) AS prev_closing
    FROM fact_inventory_sim
),
rec_sum AS (
    SELECT base_set, approach, month_key,
           sum(CASE WHEN level = 'sku' THEN forecast_units END)   AS sku_sum,
           sum(CASE WHEN level = 'total' THEN forecast_units END) AS total
    FROM fact_reconciled_forecast
    WHERE approach <> 'base'
    GROUP BY ALL
),
sim_counts AS (
    SELECT p.policy_id, count(s.policy_id) AS n
    FROM dim_policy p LEFT JOIN fact_inventory_sim s USING (policy_id)
    GROUP BY p.policy_id
)
SELECT 'dim_sku has 30 unique SKUs' AS check_name,
       abs((SELECT count(DISTINCT sku) FROM dim_sku) - 30) AS failed_rows
UNION ALL
SELECT 'fact_demand is a full SKU x month grid',
       abs((SELECT count(*) FROM fact_demand) - (SELECT count(*) FROM dim_sku) * (SELECT count(*) FROM dim_month))
UNION ALL
SELECT 'fact_demand reconciles with raw units',
       CASE WHEN abs((SELECT sum(units) FROM fact_demand) - (SELECT units FROM raw)) < 1e-6 THEN 0 ELSE 1 END
UNION ALL
SELECT 'large + base units = units',
       (SELECT count(*) FROM fact_demand WHERE abs(large_units + base_units - units) > 1e-9)
UNION ALL
SELECT 'quantiles increase with tau',
       (SELECT count(*) FROM q_lag WHERE prev_q IS NOT NULL AND quantile_units < prev_q - 1e-9)
UNION ALL
SELECT 'quantile actuals match demand (1-month windows)',
       (SELECT count(*) FROM fact_quantile_forecast q
        JOIN fact_demand d ON d.sku_key = q.sku_key AND d.month_key = q.origin_month_key
        WHERE q.window_months = 1 AND abs(q.actual_units - d.units) > 1e-9)
UNION ALL
SELECT 'reconciled SKUs add up to the total',
       (SELECT count(*) FROM rec_sum WHERE abs(sku_sum - total) > 1e-6)
UNION ALL
SELECT 'reconciled actual total matches demand',
       (SELECT count(*) FROM fact_reconciled_forecast r
        JOIN (SELECT month_key, sum(units) AS units FROM fact_demand GROUP BY month_key) d USING (month_key)
        WHERE r.level = 'total' AND abs(r.actual_units - d.units) > 1e-6)
UNION ALL
SELECT 'inventory balance: closing = opening + receipts - sales',
       (SELECT count(*) FROM fact_inventory_sim WHERE abs(closing - (opening + receipts - sales)) > 1e-6)
UNION ALL
SELECT 'inventory continuity: opening = previous closing',
       (SELECT count(*) FROM inv_lag WHERE prev_closing IS NOT NULL AND abs(opening - prev_closing) > 1e-6)
UNION ALL
SELECT 'sales between 0 and demand, lost = demand - sales',
       (SELECT count(*) FROM fact_inventory_sim
        WHERE sales < -1e-9 OR sales > demand + 1e-9 OR abs(lost - (demand - sales)) > 1e-6)
UNION ALL
SELECT 'no negative stock or orders',
       (SELECT count(*) FROM fact_inventory_sim WHERE closing < -1e-9 OR opening < -1e-9 OR order_qty < -1e-9)
UNION ALL
SELECT 'simulated demand matches fact_demand',
       (SELECT count(*) FROM fact_inventory_sim s
        JOIN fact_demand d USING (sku_key, month_key) WHERE abs(s.demand - d.units) > 1e-9)
UNION ALL
SELECT 'every policy simulated for every SKU-month',
       (SELECT count(*) FROM sim_counts WHERE n <> (SELECT count(*) FROM dim_sku) * {sim_months})
UNION ALL
SELECT 'plan: position = on hand + in transit, order = max(S - position, 0)',
       (SELECT count(*) FROM fact_replenishment_plan
        WHERE abs(inventory_position - (on_hand + in_transit)) > 1e-6
           OR abs(recommended_order - greatest(order_up_to - inventory_position, 0)) > 1e-6)
UNION ALL
SELECT 'override log actuals match demand',
       (SELECT count(*) FROM fact_override_log o
        JOIN fact_demand d USING (sku_key, month_key) WHERE abs(o.actual_units - d.units) > 1e-9)
UNION ALL
SELECT 'service targets within (0, 1)',
       (SELECT count(*) FROM fact_replenishment_plan WHERE service_target <= 0 OR service_target >= 1)
