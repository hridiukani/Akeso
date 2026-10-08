import pytest

from keywords import keywords
from stopwords import stop_words


def test_simple_sentence() -> None:
    assert keywords("The cat and the hat") == ["cat", "hat"]


def test_words_are_kept_once_in_order() -> None:
    assert keywords("Dog bites dog; dog wins.") == ["dog", "bites", "wins"]


def test_french() -> None:
    assert keywords("Le chat et le chapeau", "fr") == ["chat", "chapeau"]


def test_unknown_language() -> None:
    with pytest.raises(ValueError):
        stop_words("xx")
