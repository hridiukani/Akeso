-- Customers whose successful payments in H1 2026 add up to more than $500.
SELECT c.customer_id,
       c.name,
       SUM(p.amount) AS total_paid
FROM customers AS c
JOIN payments AS p ON p.customer_id = c.customer_id
WHERE p.status = 'succeeded'
  AND p.paid_at >= '2026-01-01'
  AND p.paid_at < '2026-07-01'
GROUP BY c.customer_id, c.name
HAVING SUM(p.amount) > 500;
