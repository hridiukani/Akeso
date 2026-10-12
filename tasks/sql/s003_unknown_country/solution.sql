-- Customers with no country on record, by the year they signed up.
SELECT strftime('%Y', signed_up_at) AS signup_year,
       COUNT(*) AS customers
FROM customers
WHERE country = NULL
  AND signed_up_at < '2026-07-01'
GROUP BY signup_year;
