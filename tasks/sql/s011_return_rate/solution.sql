-- Return rate per category for orders placed in 2025: units returned / units sold.
SELECT p.category,
       SUM(r.returned) / SUM(i.quantity) AS return_rate
FROM order_items AS i
JOIN orders AS o ON o.order_id = i.order_id
JOIN products AS p ON p.product_id = i.product_id
LEFT JOIN (
    SELECT order_id, product_id, SUM(quantity) AS returned
    FROM returns
    WHERE returned_at < '2026-07-01'
    GROUP BY order_id, product_id
) AS r ON r.order_id = i.order_id AND r.product_id = i.product_id
WHERE o.ordered_at >= '2025-01-01'
  AND o.ordered_at < '2026-01-01'
GROUP BY p.category;
