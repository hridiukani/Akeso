-- Return rate per category for orders placed in 2025: units returned / units sold.
WITH sold AS (
    SELECT i.product_id,
           SUM(i.quantity) AS units,
           SUM(COALESCE(r.returned, 0)) AS returned
    FROM order_items AS i
    JOIN orders AS o ON o.order_id = i.order_id
    LEFT JOIN (
        SELECT order_id, product_id, SUM(quantity) AS returned
        FROM returns
        WHERE returned_at < '2026-07-01'
        GROUP BY order_id, product_id
    ) AS r ON r.order_id = i.order_id AND r.product_id = i.product_id
    WHERE o.ordered_at >= '2025-01-01'
      AND o.ordered_at < '2026-01-01'
    GROUP BY i.product_id
)
SELECT p.category,
       1.0 * SUM(s.returned) / SUM(s.units) AS return_rate
FROM products AS p
LEFT JOIN sold AS s ON s.product_id = p.product_id
GROUP BY p.category;
