from keywords import keywords


def test_extra_stop_words_are_ignored() -> None:
    assert keywords("The cat and the hat", extra_stop_words=("cat",)) == ["hat"]


def test_extra_stop_words_ignore_case() -> None:
    assert keywords("Big red dog", extra_stop_words=("RED",)) == ["big", "dog"]
