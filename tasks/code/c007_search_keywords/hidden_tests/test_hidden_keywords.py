from keywords import keywords
from stopwords import stop_words


def test_extra_words_never_leak_into_later_calls() -> None:
    assert keywords("red green blue", extra_stop_words=("green",)) == ["red", "blue"]
    assert keywords("red green blue") == ["red", "green", "blue"]
    assert keywords("red green blue", extra_stop_words=("red", "blue")) == ["green"]
    assert keywords("red green blue") == ["red", "green", "blue"]


def test_the_stop_word_list_itself_never_changes() -> None:
    before = list(stop_words("en"))
    keywords("anything at all", extra_stop_words=("anything", "all"))
    assert stop_words("en") == before


def test_languages_stay_separate() -> None:
    assert keywords("pour le plaisir", "fr", extra_stop_words=("plaisir",)) == []
    assert keywords("pour le plaisir", "fr") == ["plaisir"]
    assert keywords("the pleasure is mine") == ["pleasure", "mine"]


def test_digits_and_punctuation_split_words() -> None:
    assert keywords("Route66: the mother-road") == ["route", "mother", "road"]
