-- Orders placed and amount spent per customer, first half of 2026.
SELECT o.customer_id,
       COUNT(*) AS orders,
       SUM(i.quantity * i.unit_price * (1 - COALESCE(i.discount, 0))) AS spent
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.order_id
WHERE o.ordered_at >= '2026-01-01'
  AND o.ordered_at < '2026-07-01'
GROUP BY o.customer_id;
