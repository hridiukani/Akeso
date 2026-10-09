-- A small online store: customers place orders for products, some items come back.
-- Timestamps are 'YYYY-MM-DD HH:MM:SS' in UTC. Money is in US dollars.

CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    city         TEXT,             -- NULL when unknown
    joined_at    TEXT    NOT NULL
);

CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    category     TEXT    NOT NULL,
    price        REAL    NOT NULL  -- current list price
);

CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers (customer_id),
    ordered_at   TEXT    NOT NULL
);

-- One row per product in an order. The line's amount is
-- quantity * unit_price * (1 - discount), where a NULL discount means no discount.
CREATE TABLE order_items (
    order_id     INTEGER NOT NULL REFERENCES orders (order_id),
    product_id   INTEGER NOT NULL REFERENCES products (product_id),
    quantity     INTEGER NOT NULL,
    unit_price   REAL    NOT NULL, -- the price when ordered
    discount     REAL,             -- a fraction such as 0.1; NULL means none
    PRIMARY KEY (order_id, product_id)
);

-- Items sent back. One order line can be returned in several parts (several rows).
CREATE TABLE returns (
    return_id     INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    product_id    INTEGER NOT NULL,
    returned_at   TEXT    NOT NULL,
    quantity      INTEGER NOT NULL,
    refund_amount REAL,            -- NULL while the refund hasn't been processed yet
    FOREIGN KEY (order_id, product_id) REFERENCES order_items (order_id, product_id)
);

-- Every status an order went through, in time order:
-- placed -> paid -> shipped -> delivered, or cancelled (after placed or paid).
CREATE TABLE order_events (
    event_id     INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders (order_id),
    status       TEXT    NOT NULL CHECK (status IN ('placed', 'paid', 'shipped', 'delivered', 'cancelled')),
    happened_at  TEXT    NOT NULL
);
