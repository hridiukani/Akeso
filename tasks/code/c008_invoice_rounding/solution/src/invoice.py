"""Usage invoices: metered items priced per unit, sales tax, and the printed invoice.

Money rule (from finance): every amount is rounded to whole cents, with exact halves
rounded up, at each step: each line, then the tax.
"""

from decimal import ROUND_HALF_UP, Decimal

Line = tuple[str, int, str]  # (description, quantity, unit price as a string, e.g. "0.075")


def to_cents(amount: Decimal) -> Decimal:
    """Round an amount to whole cents, exact halves up. Decimal, because binary floats
    can't hold amounts like 0.225 exactly and would round them the wrong way."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def line_total(quantity: int, unit_price: str) -> Decimal:
    return to_cents(quantity * Decimal(unit_price))


def format_invoice(lines: list[Line], tax_rate: str) -> str:
    """The printed invoice: one row per line, then subtotal, tax and total."""
    totals = [line_total(quantity, price) for _, quantity, price in lines]
    subtotal = to_cents(sum(totals, Decimal(0)))
    tax = to_cents(subtotal * Decimal(tax_rate))
    rows = [f"{description}: {quantity} x ${price} = ${total:,.2f}"
            for (description, quantity, price), total in zip(lines, totals)]
    rows.append(f"Subtotal: ${subtotal:,.2f}")
    rows.append(f"Tax ({_percent(tax_rate)}%): ${tax:,.2f}")
    rows.append(f"Total: ${subtotal + tax:,.2f}")
    return "\n".join(rows)


def _percent(rate: str) -> str:
    return f"{float(rate) * 100:g}"
