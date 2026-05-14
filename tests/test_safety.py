import pytest

from bot.config import MAX_GERMAN_LENGTH, MAX_TAGS_PER_WORD, MAX_TRANSLATION_LENGTH
from bot.safety import LimitExceeded, validate_tags_per_word, validate_word_lengths


def test_rejects_long_german_field():
    word = {
        "german": "x" * (MAX_GERMAN_LENGTH + 1),
        "translation": "fast",
        "plural": "",
        "partizip_ii": "",
        "irregular_forms": None,
    }

    with pytest.raises(LimitExceeded, match="German word is too long"):
        validate_word_lengths(word)


def test_rejects_long_translation():
    word = {
        "german": "schnell",
        "translation": "x" * (MAX_TRANSLATION_LENGTH + 1),
        "plural": "",
        "partizip_ii": "",
        "irregular_forms": None,
    }

    with pytest.raises(LimitExceeded, match="Translation is too long"):
        validate_word_lengths(word)


def test_rejects_too_many_tags_per_word():
    existing = ",".join(f"tag{i}" for i in range(MAX_TAGS_PER_WORD))

    with pytest.raises(LimitExceeded, match="tags per word"):
        validate_tags_per_word(existing, "new")


def test_existing_tag_does_not_exceed_word_tag_limit():
    existing = ",".join(f"tag{i}" for i in range(MAX_TAGS_PER_WORD))

    validate_tags_per_word(existing, "tag0")
