from invoice import format_invoice


def test_storage_invoice() -> None:
    assert format_invoice([("Storage (GB-month)", 120, "0.023")], "0.08") == (
        "Storage (GB-month): 120 x $0.023 = $2.76\n"
        "Subtotal: $2.76\n"
        "Tax (8%): $0.22\n"
        "Total: $2.98"
    )


def test_half_a_cent_rounds_up() -> None:
    assert format_invoice([("API calls", 3, "0.075")], "0.10") == (
        "API calls: 3 x $0.075 = $0.23\n"
        "Subtotal: $0.23\n"
        "Tax (10%): $0.02\n"
        "Total: $0.25"
    )


def test_several_lines() -> None:
    assert format_invoice(
        [("API calls", 7, "0.145"), ("Storage (GB-month)", 40, "0.023"), ("Support plan", 1, "29.00")], "0.0825"
    ) == (
        "API calls: 7 x $0.145 = $1.02\n"
        "Storage (GB-month): 40 x $0.023 = $0.92\n"
        "Support plan: 1 x $29.00 = $29.00\n"
        "Subtotal: $30.94\n"
        "Tax (8.25%): $2.55\n"
        "Total: $33.49"
    )


def test_tax_rounds_half_up_too() -> None:
    assert format_invoice([("Support hours", 2, "2.15")], "0.15").splitlines()[-2:] == [
        "Tax (15%): $0.65",
        "Total: $4.95",
    ]
