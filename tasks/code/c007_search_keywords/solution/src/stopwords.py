"""Stop words: common words that carry no meaning on their own, per language."""

from functools import lru_cache

_WORDS = {
    "en": "a an and are as at be but by for from has have in is it of on or that the this to was with",
    "fr": "au aux avec ce dans de des du elle en et il je la le les mais ne nous ou par pas pour que qui sur un une",
}


@lru_cache(maxsize=None)  # building the list is cheap, but it's asked for on every search
def stop_words(language: str) -> list[str]:
    """The stop words for a language code such as "en"."""
    try:
        return _WORDS[language].split()
    except KeyError:
        raise ValueError(f"no stop words for language {language!r}") from None
