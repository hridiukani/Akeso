-- Q2 2026 revenue from customers in Germany, for every plan (0 for plans with none).
SELECT pl.name AS plan,
       COALESCE(SUM(p.amount), 0) AS revenue
FROM plans AS pl
LEFT JOIN subscriptions AS s ON s.plan_id = pl.plan_id
LEFT JOIN customers AS c ON c.customer_id = s.customer_id AND c.country = 'DE'
LEFT JOIN payments AS p ON p.subscription_id = s.subscription_id
                       AND c.customer_id IS NOT NULL
                       AND p.status = 'succeeded'
                       AND p.paid_at >= '2026-04-01'
                       AND p.paid_at < '2026-07-01'
GROUP BY pl.name;
