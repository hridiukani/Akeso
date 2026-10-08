from csvrow import split_row


def test_plain_fields() -> None:
    assert split_row("a,b,c") == ["a", "b", "c"]


def test_quoted_field_with_a_comma() -> None:
    assert split_row('id,"Smith, Jane",42') == ["id", "Smith, Jane", "42"]


def test_empty_fields_are_kept() -> None:
    assert split_row("a,,b,") == ["a", "", "b", ""]


def test_empty_quoted_field() -> None:
    assert split_row('a,"",b') == ["a", "", "b"]


def test_doubled_quotes_inside_a_quoted_field() -> None:
    assert split_row('7,"He said ""hi""",ok') == ["7", 'He said "hi"', "ok"]
