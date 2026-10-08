"""Split one line of a delimited text file into fields."""


def split_row(line: str, delimiter: str = ",") -> list[str]:
    """Split line into fields. A field may be wrapped in double quotes, so it can contain
    the delimiter; inside quotes, a doubled quote ("") stands for one quote character."""
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields
