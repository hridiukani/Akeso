-- Each customer's latest plan: the plan of their most recent subscription that started
-- on or before 2026-06-30 (cancelled customers included).
WITH ranked AS (
    SELECT s.customer_id,
           s.plan_id,
           ROW_NUMBER() OVER (PARTITION BY s.customer_id ORDER BY s.plan_id DESC) AS rn
    FROM subscriptions AS s
    WHERE s.start_date <= '2026-06-30'
)
SELECT r.customer_id,
       pl.name AS latest_plan
FROM ranked AS r
JOIN plans AS pl ON pl.plan_id = r.plan_id
WHERE r.rn = 1;
