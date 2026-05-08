"""Tests for bot/handlers/_shared.py — cross-flow helpers (formatter,
arg-parser, log sanitizer)."""

import json

from bot.handlers import _format_word_tables, _parse_quiz_args, _safe_log


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
        forms = {"ich": "fahre", "du": "fährst", "er": "fährt"}
        words = [
            {
                "id": 2,
                "part_of_speech": "v",
                "german": "fahren",
                "partizip_ii": "ist gefahren",
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
                "partizip_ii": "hat gemacht",
                "translation": "to do",
                "irregular_forms": None,
            }
        ]
        text = _format_word_tables(words)
        assert "machen" in text
        assert "hat gemacht" in text

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
