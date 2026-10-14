-- Top 3 products by units kept (sold minus returned) in each category, first half of 2026.
WITH units AS (
    SELECT p.category, p.name,
           SUM(i.quantity) - SUM(COALESCE(r.quantity, 0)) AS units
    FROM order_items AS i
    JOIN orders AS o ON o.order_id = i.order_id
    JOIN products AS p ON p.product_id = i.product_id
    LEFT JOIN returns AS r ON r.order_id = i.order_id
                          AND r.product_id = i.product_id
                          AND r.returned_at < '2026-07-01'
    WHERE o.ordered_at >= '2026-01-01'
      AND o.ordered_at < '2026-07-01'
    GROUP BY p.category, p.name
),
ranked AS (
    SELECT category, name, units,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY units DESC) AS rnk
    FROM units
)
SELECT category, rnk, name, units
FROM ranked
WHERE rnk <= 3
ORDER BY category, rnk;
