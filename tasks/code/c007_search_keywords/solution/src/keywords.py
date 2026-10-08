"""Keyword extraction for the search index."""

import re

from stopwords import stop_words

_WORD = re.compile(r"[^\W\d_]+")  # runs of letters, in any alphabet


def keywords(text: str, language: str = "en", extra_stop_words: tuple[str, ...] = ()) -> list[str]:
    """The words of text worth indexing: lowercased, stop words removed, each kept once in
    order of first appearance. extra_stop_words are ignored too, for this call only."""
    # A new set: the cached list from stop_words is shared by every call and must not change.
    ignored = set(stop_words(language)) | {word.lower() for word in extra_stop_words}
    result: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word not in ignored and word not in result:
            result.append(word)
    return result
