-- Orders per month and month-over-month growth, July 2025 to June 2026, in month order.
WITH monthly AS (
    SELECT strftime('%Y-%m', ordered_at) AS month, COUNT(*) AS orders
    FROM orders
    WHERE ordered_at >= '2025-07-01'
      AND ordered_at < '2026-07-01'
    GROUP BY month
)
SELECT month,
       orders,
       ROUND(1.0 * (orders - LAG(orders) OVER (ORDER BY month)) / LAG(orders) OVER (ORDER BY month), 4) AS growth
FROM monthly
ORDER BY month;
