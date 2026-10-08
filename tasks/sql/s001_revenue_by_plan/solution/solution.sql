-- Total revenue by plan for the 90 days ending 2026-06-30.
SELECT pl.name AS plan,
       SUM(p.amount) AS revenue
FROM payments AS p
JOIN subscriptions AS s ON s.subscription_id = p.subscription_id
JOIN plans AS pl ON pl.plan_id = s.plan_id
WHERE p.status = 'succeeded'
  AND p.paid_at >= date('2026-06-30', '-89 days')
  AND p.paid_at < date('2026-06-30', '+1 day')
GROUP BY pl.name;
