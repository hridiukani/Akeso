-- Top 3 products by units sold in each category, first half of 2026.
WITH units AS (
    SELECT p.category, p.name, SUM(i.quantity) AS units
    FROM order_items AS i
    JOIN orders AS o ON o.order_id = i.order_id
    JOIN products AS p ON p.product_id = i.product_id
    WHERE o.ordered_at >= '2026-01-01'
      AND o.ordered_at < '2026-07-01'
    GROUP BY p.category, p.name
),
ranked AS (
    SELECT category, name, units,
           RANK() OVER (PARTITION BY category ORDER BY units DESC) AS rnk
    FROM units
)
SELECT category, rnk, name, units
FROM ranked
WHERE rnk <= 3
ORDER BY category, rnk, name;
