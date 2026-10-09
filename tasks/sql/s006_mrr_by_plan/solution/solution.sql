-- Monthly recurring revenue (MRR) by plan, as of 2026-06-30.
SELECT pl.name AS plan,
       SUM(CASE pl.billing_period WHEN 'annual' THEN pl.price / 12.0 ELSE pl.price END) AS mrr
FROM subscriptions AS s
JOIN plans AS pl ON pl.plan_id = s.plan_id
WHERE s.start_date <= '2026-06-30'
  AND (s.end_date IS NULL OR s.end_date > '2026-06-30')
GROUP BY pl.name;
