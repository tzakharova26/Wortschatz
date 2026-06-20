"""Tests for bot/handlers/_shared.py — cross-flow helpers (formatter,
arg-parser, log sanitizer, TTL pending state)."""

import json
import time

from bot.handlers import (
    _format_word_tables,
    _parse_quiz_args,
    _safe_log,
    pending_pop,
    pending_set,
)


class TestFormatWordTables:
    def test_nouns(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "n",
                "german": "Katze",
                "article": "die",
                "plural": "Katzen",
                "translation": "cat",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "Nouns" in text
        assert "die" in text
        assert "Katze" in text
        assert "Katzen" in text
        assert "[1]" in text

    def test_verbs_with_forms(self):
        forms = {
            "partizip_ii": "ist gefahren",
            "ich": "fahre",
            "du": "fährst",
            "er": "fährt",
        }
        words = [
            {
                "id": 2,
                "part_of_speech": "v",
                "german": "fahren",
                "translation": "to drive",
                "irregular_forms": json.dumps(forms),
            }
        ]
        text = _format_word_tables(words)
        assert "Verbs" in text
        assert "fahren" in text
        assert "ist gefahren" in text
        assert "ich: fahre" in text
        assert "du: fährst" in text

    def test_verbs_without_forms(self):
        words = [
            {
                "id": 3,
                "part_of_speech": "v",
                "german": "machen",
                "translation": "to do",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "machen" in text
        assert "to do" in text

    def test_adjectives(self):
        words = [
            {
                "id": 4,
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "fast",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "Adjectives" in text
        assert "schnell" in text

    def test_mixed_pos_grouped(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "n",
                "german": "Katze",
                "article": "die",
                "plural": "Katzen",
                "translation": "cat",
                "irregular_forms": None,
            },
            {
                "id": 2,
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "fast",
                "irregular_forms": None,
            },
        ]
        text = _format_word_tables(words)
        assert text.index("Nouns") < text.index("Adjectives")

    def test_empty_list(self):
        text = _format_word_tables([])
        assert text == ""

    def test_show_ids_false_drops_id_prefix(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "n",
                "german": "Katze",
                "article": "die",
                "plural": "Katzen",
                "translation": "cat",
                "irregular_forms": None,
            },
            {
                "id": 2,
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "fast",
                "irregular_forms": None,
            },
        ]
        text = _format_word_tables(words, show_ids=False)
        assert "[1]" not in text
        assert "[2]" not in text
        # Word data still present
        assert "Katze" in text
        assert "schnell" in text


class TestFormatWordTablesEdgeCases:
    def test_noun_no_article(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "n",
                "german": "Katze",
                "article": None,
                "plural": "Katzen",
                "translation": "cat",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "?" in text
        assert "Katze" in text

    def test_noun_no_plural(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "n",
                "german": "Katze",
                "article": "die",
                "plural": None,
                "translation": "cat",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "—" in text
        assert "Katze" in text

    def test_html_escaped_in_german(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "adj",
                "german": "<script>",
                "translation": "evil",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_html_escaped_in_translation(self):
        words = [
            {
                "id": 1,
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "<b>fast</b>",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "<b>fast</b>" not in text
        assert "&lt;b&gt;" in text


class TestParseQuizArgs:
    def test_no_args(self):
        assert _parse_quiz_args([]) == (None, None)

    def test_size_only(self):
        assert _parse_quiz_args(["5"]) == (5, None)

    def test_tag_only(self):
        assert _parse_quiz_args(["animals"]) == (None, "animals")

    def test_size_then_tag(self):
        assert _parse_quiz_args(["5", "animals"]) == (5, "animals")

    def test_tag_then_size(self):
        assert _parse_quiz_args(["animals", "5"]) == (5, "animals")

    def test_strips_hash(self):
        assert _parse_quiz_args(["#animals"]) == (None, "animals")


class TestSafeLog:
    def test_strips_control_chars(self):
        assert _safe_log("hello\nworld") == "hello?world"
        assert _safe_log("\x1b[31mred\x1b[0m") == "?[31mred?[0m"

    def test_truncates_long(self):
        result = _safe_log("a" * 500)
        assert result.endswith("...")
        assert len(result) <= 220  # within reason

    def test_none(self):
        assert _safe_log(None) == ""
        assert _safe_log("") == ""


class TestPendingTTL:
    def test_set_and_pop_round_trip(self, fake_context):
        pending_set(fake_context, "k", [1, 2, 3], ttl=60)
        assert pending_pop(fake_context, "k") == [1, 2, 3]
        # After pop, key is gone
        assert pending_pop(fake_context, "k") is None

    def test_pop_missing_returns_none(self, fake_context):
        assert pending_pop(fake_context, "never_set") is None

    def test_expired_entry_returns_none(self, fake_context, monkeypatch):
        """A value past its expires_at should pop as None."""
        pending_set(fake_context, "k", "payload", ttl=10)
        # Fast-forward monotonic by 11s so the entry is expired.
        real_monotonic = time.monotonic
        # Capture set-time to fake "now > expires_at" reliably.
        from bot.handlers import _shared as shared_module

        monkeypatch.setattr(shared_module.time, "monotonic", lambda: real_monotonic() + 1000)
        assert pending_pop(fake_context, "k") is None

    def test_legacy_raw_value_tolerated(self, fake_context):
        """A bare list (not wrapped) is returned as-is — keeps test seeding simple."""
        fake_context.user_data["raw"] = [99, 100]
        assert pending_pop(fake_context, "raw") == [99, 100]
