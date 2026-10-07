-- A small SaaS billing database: customers subscribe to plans and pay for them.
-- Dates are ISO-8601 text. Money is in US dollars.

CREATE TABLE plans (
    plan_id         INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,
    billing_period  TEXT    NOT NULL CHECK (billing_period IN ('monthly', 'annual')),
    price           REAL    NOT NULL  -- list price per billing period
);

CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    email           TEXT,             -- NULL when never collected
    country         TEXT,             -- ISO country code; NULL when unknown
    signed_up_at    TEXT    NOT NULL  -- 'YYYY-MM-DD HH:MM:SS'
);

-- One row per period a customer spent on one plan. Changing plan ends the current
-- subscription and starts a new one on the same day.
CREATE TABLE subscriptions (
    subscription_id INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers (customer_id),
    plan_id         INTEGER NOT NULL REFERENCES plans (plan_id),
    start_date      TEXT    NOT NULL, -- 'YYYY-MM-DD', first day on this plan
    end_date        TEXT,             -- 'YYYY-MM-DD', first day no longer on it; NULL while active
    end_reason      TEXT CHECK (end_reason IN ('plan_change', 'cancelled'))  -- NULL while active
);

-- Every charge attempt. Only 'succeeded' payments are revenue; a refunded payment was
-- collected and later returned in full.
CREATE TABLE payments (
    payment_id      INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions (subscription_id),
    customer_id     INTEGER NOT NULL REFERENCES customers (customer_id),
    paid_at         TEXT    NOT NULL, -- 'YYYY-MM-DD HH:MM:SS'
    amount          REAL    NOT NULL, -- after any discount or proration
    status          TEXT    NOT NULL CHECK (status IN ('succeeded', 'failed', 'refunded'))
);
