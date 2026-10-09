-- Net revenue per category for orders placed in Q2 2026: sales minus refunds.
SELECT p.category,
       SUM(i.quantity * i.unit_price * (1 - i.discount)) - SUM(r.refund_amount) AS net_revenue
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
JOIN products AS p ON p.product_id = i.product_id
LEFT JOIN returns AS r ON r.order_id = i.order_id
                      AND r.product_id = i.product_id
                      AND r.returned_at < '2026-07-01'
WHERE o.ordered_at >= '2026-04-01'
  AND o.ordered_at < '2026-07-01'
GROUP BY p.category;
