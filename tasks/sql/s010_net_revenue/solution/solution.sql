-- Net revenue per category for orders placed in Q2 2026: sales minus refunds.
WITH lines AS (
    SELECT p.category, i.order_id, i.product_id,
           i.quantity * i.unit_price * (1 - COALESCE(i.discount, 0)) AS amount
    FROM orders AS o
    JOIN order_items AS i ON i.order_id = o.order_id
    JOIN products AS p ON p.product_id = i.product_id
    WHERE o.ordered_at >= '2026-04-01'
      AND o.ordered_at < '2026-07-01'
),
refunds AS (
    SELECT order_id, product_id, SUM(COALESCE(refund_amount, 0)) AS refunded
    FROM returns
    WHERE returned_at < '2026-07-01'
    GROUP BY order_id, product_id
)
SELECT l.category,
       SUM(l.amount) - COALESCE(SUM(r.refunded), 0) AS net_revenue
FROM lines AS l
LEFT JOIN refunds AS r ON r.order_id = l.order_id AND r.product_id = l.product_id
GROUP BY l.category;
