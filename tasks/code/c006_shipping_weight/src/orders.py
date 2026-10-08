"""Order lines look like "MUG-01 x 3": a product code and a quantity."""

from catalog import weight_grams


def parse_line(line: str) -> tuple[str, int]:
    sku, sep, quantity = line.partition(" x ")
    if not sep or not quantity.strip().isdigit() or int(quantity) < 1:
        raise ValueError(f"bad order line {line!r}; expected e.g. 'MUG-01 x 3'")
    return sku.strip(), int(quantity)


def total_weight_kg(lines: list[str]) -> float:
    """Total weight of an order, in kilograms."""
    return sum(quantity * weight_grams(sku) for sku, quantity in map(parse_line, lines))
