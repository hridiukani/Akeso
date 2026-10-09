-- Monthly customer churn for Q2 2026, in month order.
WITH months(month_start, next_start) AS (
    VALUES ('2026-04-01', '2026-05-01'), ('2026-05-01', '2026-06-01'), ('2026-06-01', '2026-07-01')
),
active_on AS (
    -- (customer, day) pairs where the customer has an active subscription on that day.
    SELECT DISTINCT m.month_start, m.next_start, s.customer_id
    FROM months AS m
    JOIN subscriptions AS s
      ON s.start_date <= m.month_start
     AND (s.end_date IS NULL OR s.end_date > m.month_start)
),
churn AS (
    SELECT a.month_start,
           COUNT(*) AS active_at_start,
           SUM(NOT EXISTS (
               SELECT 1 FROM subscriptions AS s
               WHERE s.customer_id = a.customer_id
                 AND s.start_date <= a.next_start
                 AND (s.end_date IS NULL OR s.end_date > a.next_start)
           )) AS churned
    FROM active_on AS a
    GROUP BY a.month_start
)
SELECT substr(month_start, 1, 7) AS month,
       active_at_start,
       churned,
       ROUND(1.0 * churned / active_at_start, 4) AS churn_rate
FROM churn
ORDER BY month_start;
