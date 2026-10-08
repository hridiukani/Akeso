# search

Keyword extraction for a small search index.

## `stopwords.stop_words(language)`

The list of stop words (common words like "the" or "and") for a language code: `"en"`
or `"fr"`. Other codes raise `ValueError`.

## `keywords.keywords(text, language="en", extra_stop_words=())`

The words of `text` worth indexing:

- lowercased, split into runs of letters (digits and punctuation separate words)
- without the language's stop words
- without `extra_stop_words`, which apply to **this call only** (case doesn't matter)
- each word once, in order of first appearance

Examples:

- `keywords("The cat and the hat")` returns `["cat", "hat"]`
- `keywords("The cat and the hat", extra_stop_words=("cat",))` returns `["hat"]`
- `keywords("Le chat et le chapeau", "fr")` returns `["chat", "chapeau"]`

## Running the tests

```
python -m pytest
```
