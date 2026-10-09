-- Monthly customer churn for Q2 2026, in month order.
WITH months(month_start, next_start) AS (
    VALUES ('2026-04-01', '2026-05-01'), ('2026-05-01', '2026-06-01'), ('2026-06-01', '2026-07-01')
),
active_at_start AS (
    SELECT m.month_start, s.subscription_id, s.end_date, m.next_start
    FROM months AS m
    JOIN subscriptions AS s
      ON s.start_date <= m.month_start
     AND (s.end_date IS NULL OR s.end_date >= m.month_start)
)
SELECT substr(month_start, 1, 7) AS month,
       COUNT(*) AS active_at_start,
       SUM(end_date IS NOT NULL AND end_date <= next_start) AS churned,
       ROUND(1.0 * SUM(end_date IS NOT NULL AND end_date <= next_start) / COUNT(*), 4) AS churn_rate
FROM active_at_start
GROUP BY month_start
ORDER BY month_start;
