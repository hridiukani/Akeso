import pytest

from csvrow import split_row


@pytest.mark.parametrize(("line", "fields"), [
    ('"""quoted"" start",x', ['"quoted" start', "x"]),
    ('x,"end ""quoted"""', ["x", 'end "quoted"']),
    ('""""', ['"']),
    ('"a""b""c"', ['a"b"c']),
    ('"",""', ["", ""]),
    ('"6"" pipe, 2"" wide",in stock', ['6" pipe, 2" wide', "in stock"]),
])
def test_escaped_quotes_anywhere(line, fields) -> None:
    assert split_row(line) == fields


def test_other_delimiters() -> None:
    assert split_row('a;"b;""c""";d', ";") == ["a", 'b;"c"', "d"]
    assert split_row('1\t"tab\there"\t""', "\t") == ["1", "tab\there", ""]
