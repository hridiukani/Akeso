import pytest

from invoice import format_invoice


@pytest.mark.parametrize(("lines", "rate", "expected"), [
    ([("SMS messages", 3, "0.155"), ("Voice minutes", 3, "0.185")], "0.06",
     ["SMS messages: 3 x $0.155 = $0.47", "Voice minutes: 3 x $0.185 = $0.56", "Subtotal: $1.03", "Tax (6%): $0.06", "Total: $1.09"]),
    ([("Compute hours", 11, "0.135"), ("API calls", 1, "0.045")], "0.0725",
     ["Compute hours: 11 x $0.135 = $1.49", "API calls: 1 x $0.045 = $0.05", "Subtotal: $1.54", "Tax (7.25%): $0.11", "Total: $1.65"]),
    ([("Seats", 12, "1234.505")], "0.08",
     ["Seats: 12 x $1234.505 = $14,814.06", "Subtotal: $14,814.06", "Tax (8%): $1,185.12", "Total: $15,999.18"]),
    ([("Nothing billed", 0, "0.075")], "0.08",
     ["Nothing billed: 0 x $0.075 = $0.00", "Subtotal: $0.00", "Tax (8%): $0.00", "Total: $0.00"]),
    ([("API calls", 3, "0.175"), ("Data transfer (GB)", 25, "0.087")], "0.05",
     ["API calls: 3 x $0.175 = $0.53", "Data transfer (GB): 25 x $0.087 = $2.18", "Subtotal: $2.71", "Tax (5%): $0.14", "Total: $2.85"]),
])
def test_other_invoices(lines, rate, expected) -> None:
    assert format_invoice(lines, rate).splitlines() == expected


@pytest.mark.parametrize(("price", "rate", "tax", "total"), [
    ("21.50", "0.05", "$1.08", "$22.58"),
    ("12.10", "0.15", "$1.82", "$13.92"),
    ("0.70", "0.05", "$0.04", "$0.74"),
])
def test_tax_halves_round_up(price, rate, tax, total) -> None:
    rows = format_invoice([("Item", 1, price)], rate).splitlines()
    assert rows[-2].endswith(tax) and rows[-1] == f"Total: {total}"
