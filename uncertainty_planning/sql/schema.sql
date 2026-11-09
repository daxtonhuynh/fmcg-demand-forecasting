-- Planning warehouse (DuckDB): a separate database from the main project's fmcg.duckdb.
-- Dimensions are keyed by surrogate integers; facts reference them.

CREATE TABLE dim_sku (
    sku_key             INTEGER PRIMARY KEY,
    sku                 VARCHAR NOT NULL UNIQUE,
    product_name        VARCHAR NOT NULL,
    brand               VARCHAR NOT NULL,
    category            VARCHAR NOT NULL,
    abc_class           VARCHAR NOT NULL,
    unit_price          DOUBLE  NOT NULL,   -- median net revenue per unit
    unit_cost           DOUBLE  NOT NULL,   -- median COGS per unit
    unit_profit         DOUBLE  NOT NULL,   -- median profit per unit (after logistics and marketing)
    unit_gross_margin   DOUBLE  NOT NULL,   -- unit_price - unit_cost
    critical_ratio_base DOUBLE  NOT NULL    -- cost-optimal service level, base assumptions
);

CREATE TABLE dim_month (
    month_key     INTEGER PRIMARY KEY,      -- yyyymm
    month         DATE    NOT NULL UNIQUE,
    year          INTEGER NOT NULL,
    month_of_year INTEGER NOT NULL,
    is_test       BOOLEAN NOT NULL
);

CREATE TABLE dim_policy (
    policy_id       VARCHAR PRIMARY KEY,    -- L{lead}|{method}|{qmethod}|{target}
    lead_time       INTEGER NOT NULL,
    family          VARCHAR NOT NULL,       -- quantile | cover
    method          VARCHAR NOT NULL,
    qmethod         VARCHAR NOT NULL,
    target_label    VARCHAR NOT NULL,
    target_value    DOUBLE,                 -- uniform service target (NULL for per-SKU or cover)
    cr_basis        VARCHAR,                -- per-SKU critical ratio: lost-sale basis
    cr_holding_rate DOUBLE,                 -- per-SKU critical ratio: holding rate
    cover_months    DOUBLE                  -- rule of thumb: months of forecast held as buffer
);

CREATE TABLE fact_demand (
    sku_key     INTEGER NOT NULL REFERENCES dim_sku (sku_key),
    month_key   INTEGER NOT NULL REFERENCES dim_month (month_key),
    units       DOUBLE  NOT NULL,
    large_units DOUBLE  NOT NULL,           -- from orders >= pre-test 90th percentile size
    base_units  DOUBLE  NOT NULL,
    PRIMARY KEY (sku_key, month_key)
);

CREATE TABLE fact_quantile_forecast (
    sku_key          INTEGER NOT NULL REFERENCES dim_sku (sku_key),
    origin_month_key INTEGER NOT NULL REFERENCES dim_month (month_key),
    window_months    INTEGER NOT NULL,
    method           VARCHAR NOT NULL,
    qmethod          VARCHAR NOT NULL,
    tau              DOUBLE  NOT NULL,
    quantile_units   DOUBLE  NOT NULL,
    point_units      DOUBLE  NOT NULL,
    actual_units     DOUBLE  NOT NULL,
    PRIMARY KEY (sku_key, origin_month_key, window_months, method, qmethod, tau)
);

CREATE TABLE fact_reconciled_forecast (
    base_set       VARCHAR NOT NULL,
    approach       VARCHAR NOT NULL,
    level          VARCHAR NOT NULL,        -- total | category | brand | sku
    series         VARCHAR NOT NULL,
    month_key      INTEGER NOT NULL REFERENCES dim_month (month_key),
    forecast_units DOUBLE  NOT NULL,
    actual_units   DOUBLE  NOT NULL,
    PRIMARY KEY (base_set, approach, level, series, month_key)
);

CREATE TABLE fact_inventory_sim (
    policy_id   VARCHAR NOT NULL REFERENCES dim_policy (policy_id),
    sku_key     INTEGER NOT NULL REFERENCES dim_sku (sku_key),
    month_key   INTEGER NOT NULL REFERENCES dim_month (month_key),
    is_test     BOOLEAN NOT NULL,
    opening     DOUBLE  NOT NULL,           -- on hand before receipts
    receipts    DOUBLE  NOT NULL,
    order_qty   DOUBLE  NOT NULL,
    demand      DOUBLE  NOT NULL,
    sales       DOUBLE  NOT NULL,
    lost        DOUBLE  NOT NULL,
    closing     DOUBLE  NOT NULL,
    order_up_to DOUBLE  NOT NULL,
    PRIMARY KEY (policy_id, sku_key, month_key)
);

CREATE TABLE fact_replenishment_plan (
    policy_id                  VARCHAR NOT NULL REFERENCES dim_policy (policy_id),
    sku_key                    INTEGER NOT NULL REFERENCES dim_sku (sku_key),
    plan_month                 DATE    NOT NULL,
    arrival_month              DATE    NOT NULL,
    lead_time_months           INTEGER NOT NULL,
    service_target             DOUBLE  NOT NULL,
    expected_demand_protection DOUBLE  NOT NULL,
    order_up_to                DOUBLE  NOT NULL,
    safety_stock               DOUBLE  NOT NULL,
    on_hand                    DOUBLE  NOT NULL,
    in_transit                 DOUBLE  NOT NULL,
    inventory_position         DOUBLE  NOT NULL,
    recommended_order          DOUBLE  NOT NULL,
    order_value_at_cost        DOUBLE  NOT NULL,
    PRIMARY KEY (policy_id, sku_key)
);

CREATE TABLE fact_override_log (
    archetype            VARCHAR NOT NULL,
    sku_key              INTEGER NOT NULL REFERENCES dim_sku (sku_key),
    month_key            INTEGER NOT NULL REFERENCES dim_month (month_key),
    statistical_forecast DOUBLE  NOT NULL,
    final_forecast       DOUBLE  NOT NULL,
    overridden           BOOLEAN NOT NULL,
    reason_code          VARCHAR,
    actual_units         DOUBLE  NOT NULL,
    PRIMARY KEY (archetype, sku_key, month_key)
);

CREATE TABLE fact_voi_run (
    visibility          DOUBLE  NOT NULL,
    seed                INTEGER NOT NULL,
    policy              VARCHAR NOT NULL,   -- cost_optimal | uniform_95
    sku_wape            DOUBLE  NOT NULL,
    total_wape          DOUBLE  NOT NULL,
    avg_inventory_value DOUBLE  NOT NULL,
    fill_rate           DOUBLE  NOT NULL,
    total_cost          DOUBLE  NOT NULL,
    PRIMARY KEY (visibility, seed, policy)
);
