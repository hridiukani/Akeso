-- Orders per month and month-over-month growth, July 2025 to June 2026, in month order.
WITH RECURSIVE months(month_start) AS (
    SELECT '2025-07-01'
    UNION ALL
    SELECT date(month_start, '+1 month') FROM months WHERE month_start < '2026-06-01'
),
monthly AS (
    SELECT substr(m.month_start, 1, 7) AS month,
           COUNT(o.order_id) AS orders
    FROM months AS m
    LEFT JOIN orders AS o ON substr(o.ordered_at, 1, 7) = substr(m.month_start, 1, 7)
    GROUP BY m.month_start
)
SELECT month,
       orders,
       ROUND(1.0 * (orders - LAG(orders) OVER (ORDER BY month))
             / NULLIF(LAG(orders) OVER (ORDER BY month), 0), 4) AS growth
FROM monthly
ORDER BY month;
