-- June 2026 orders by their status at the end of 2026-06-30.
WITH ranked AS (
    SELECT e.order_id, e.status,
           ROW_NUMBER() OVER (PARTITION BY e.order_id ORDER BY e.happened_at DESC, e.event_id DESC) AS rn
    FROM order_events AS e
    JOIN orders AS o ON o.order_id = e.order_id
    WHERE o.ordered_at >= '2026-06-01'
      AND o.ordered_at < '2026-07-01'
      AND e.happened_at < '2026-07-01'
)
SELECT status, COUNT(*) AS orders
FROM ranked
WHERE rn = 1
GROUP BY status;
