-- Successful payments and revenue per month for Q2 2026, in month order.
SELECT strftime('%Y-%m', paid_at) AS month,
       COUNT(*) AS payments,
       SUM(amount) AS revenue
FROM payments
WHERE status = 'succeeded'
  AND paid_at >= '2026-04-01'
  AND paid_at < '2026-07-01'
GROUP BY month
ORDER BY month;
