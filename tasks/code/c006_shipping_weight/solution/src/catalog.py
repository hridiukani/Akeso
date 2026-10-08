"""Product catalog. Weights are stored in grams, exactly as the warehouse system exports them."""

_PRODUCTS = {
    "MUG-01": ("Ceramic mug", 350),
    "BOOK-07": ("Hardback notebook", 620),
    "LAMP-03": ("Desk lamp", 1850),
    "CHAIR-02": ("Folding chair", 4300),
    "PEN-10": ("Gel pens, pack of 10", 95),
    "CABLE-05": ("USB cable", 30),
}


def product_name(sku: str) -> str:
    return _lookup(sku)[0]


def weight_grams(sku: str) -> int:
    """The product's weight in grams."""
    return _lookup(sku)[1]


def _lookup(sku: str) -> tuple[str, int]:
    try:
        return _PRODUCTS[sku]
    except KeyError:
        raise ValueError(f"unknown product {sku!r}") from None
