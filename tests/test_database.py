import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest

from bot.database import (
    add_quiz_history,
    add_word,
    delete_word,
    find_words_by_german,
    get_connection,
    get_due_words,
    get_quiz_types_for_word,
    get_sm2_state,
    get_stats,
    get_tags,
    get_word_by_id,
    get_words,
    get_words_by_pos,
    init_db,
    parse_irregular_forms,
    upsert_sm2_state,
)

USER_ID = 12345


class TestAddWord:
    async def test_add_noun(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "n",
            "Katze",
            "cat",
            article="die",
            plural="Katzen",
        )
        assert word_id is not None
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["german"] == "Katze"
        assert word["article"] == "die"
        assert word["plural"] == "Katzen"
        assert word["translation"] == "cat"
        assert word["part_of_speech"] == "n"

    async def test_add_verb(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "v",
            "fahren",
            "to drive",
            partizip_ii="ist gefahren",
            irregular_forms={"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"},
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["partizip_ii"] == "ist gefahren"
        import json

        forms = json.loads(word["irregular_forms"])
        assert forms["ich"] == "fahre"

    async def test_add_adjective(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["part_of_speech"] == "adj"

    async def test_add_with_tags(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "n",
            "Hund",
            "dog",
            article="der",
            plural="Hunde",
            tags="animals",
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["tags"] == "animals"

    async def test_invalid_part_of_speech(self, db):
        with pytest.raises(ValueError, match="Invalid part_of_speech"):
            await add_word(db, USER_ID, "banana", "Hund", "dog")

    async def test_empty_german(self, db):
        with pytest.raises(ValueError, match="german word cannot be empty"):
            await add_word(db, USER_ID, "adj", "", "fast")

    async def test_whitespace_german(self, db):
        with pytest.raises(ValueError, match="german word cannot be empty"):
            await add_word(db, USER_ID, "adj", "   ", "fast")

    async def test_empty_translation(self, db):
        with pytest.raises(ValueError, match="translation cannot be empty"):
            await add_word(db, USER_ID, "adj", "schnell", "")

    async def test_tags_normalized(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast", tags=" animals , food ")
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["tags"] == "animals,food"

    async def test_german_stripped(self, db):
        word_id = await add_word(db, USER_ID, "adj", "  schnell  ", "fast")
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["german"] == "schnell"

    async def test_translation_stripped(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "  fast  ")
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["translation"] == "fast"

    async def test_russian_translation(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "n",
            "Katze",
            "\u043a\u043e\u0448\u043a\u0430",
            article="die",
            plural="Katzen",
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["translation"] == "\u043a\u043e\u0448\u043a\u0430"


class TestDeleteWord:
    async def test_delete_existing(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        result = await delete_word(db, USER_ID, word_id)
        assert result is True
        words = await get_words(db, USER_ID)
        assert len(words) == 0

    async def test_delete_nonexistent(self, db):
        result = await delete_word(db, USER_ID, 999)
        assert result is False

    async def test_delete_wrong_user(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        result = await delete_word(db, 99999, word_id)
        assert result is False
        words = await get_words(db, USER_ID)
        assert len(words) == 1


class TestGetWords:
    async def test_get_all(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await add_word(db, USER_ID, "n", "Hund", "dog", article="der", plural="Hunde")
        words = await get_words(db, USER_ID)
        assert len(words) == 2

    async def test_get_by_tag(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", tags="animals")
        await add_word(db, USER_ID, "n", "Tisch", "table", tags="furniture")
        words = await get_words(db, USER_ID, tag="animals")
        assert len(words) == 1
        assert words[0]["german"] == "Katze"

    async def test_get_empty(self, db):
        words = await get_words(db, USER_ID)
        assert len(words) == 0

    async def test_different_users(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_word(db, 99999, "adj", "langsam", "slow")
        words = await get_words(db, USER_ID)
        assert len(words) == 1


class TestGetWordById:
    async def test_own_word(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word is not None
        assert word["german"] == "schnell"

    async def test_other_users_word(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        word = await get_word_by_id(db, word_id, 99999)
        assert word is None


class TestTags:
    async def test_get_tags(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", tags="animals")
        await add_word(db, USER_ID, "n", "Tisch", "table", tags="furniture")
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        tags = await get_tags(db, USER_ID)
        assert tags == ["animals", "furniture"]

    async def test_comma_separated_query(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", tags="animals,A1")
        words = await get_words(db, USER_ID, tag="animals")
        assert len(words) == 1
        words = await get_words(db, USER_ID, tag="A1")
        assert len(words) == 1

    async def test_tag_with_sql_wildcards(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast", tags="a%b")
        await add_word(db, USER_ID, "adj", "langsam", "slow", tags="axb")
        words = await get_words(db, USER_ID, tag="a%b")
        assert len(words) == 1
        assert words[0]["german"] == "schnell"


class TestWordsByPos:
    async def test_filter_by_pos(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat")
        await add_word(db, USER_ID, "v", "machen", "to do")
        await add_word(db, USER_ID, "n", "Hund", "dog")
        nouns = await get_words_by_pos(db, USER_ID, "n")
        assert len(nouns) == 2
        verbs = await get_words_by_pos(db, USER_ID, "v")
        assert len(verbs) == 1


class TestQuizTypesForWord:
    def test_noun(self):
        word = {"part_of_speech": "n", "irregular_forms": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice", "article"]

    def test_regular_verb(self):
        word = {"part_of_speech": "v", "irregular_forms": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]

    def test_irregular_verb(self):
        word = {"part_of_speech": "v", "irregular_forms": '{"ich": "fahre"}'}
        assert get_quiz_types_for_word(word) == [
            "translate",
            "multiple_choice",
            "verb_forms",
        ]

    def test_adjective(self):
        word = {"part_of_speech": "adj", "irregular_forms": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]

    def test_verb_with_empty_json_forms(self):
        word = {"part_of_speech": "v", "irregular_forms": "{}"}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]

    def test_verb_with_invalid_json_forms(self):
        word = {"part_of_speech": "v", "irregular_forms": "not json"}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]


class TestSM2State:
    async def test_upsert_and_get(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        now = datetime.now()
        await upsert_sm2_state(
            db,
            USER_ID,
            word_id,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=now,
        )
        state = await get_sm2_state(db, USER_ID, word_id, "translate")
        assert state is not None
        assert state["easiness_factor"] == 2.5
        assert state["correct_count"] == 1

    async def test_upsert_updates(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        now = datetime.now()
        await upsert_sm2_state(
            db,
            USER_ID,
            word_id,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=now,
        )
        await upsert_sm2_state(
            db,
            USER_ID,
            word_id,
            "translate",
            easiness_factor=2.6,
            interval=6,
            repetitions=2,
            correct_count=2,
            next_review=now,
        )
        state = await get_sm2_state(db, USER_ID, word_id, "translate")
        assert state["easiness_factor"] == 2.6
        assert state["correct_count"] == 2

    async def test_get_nonexistent(self, db):
        state = await get_sm2_state(db, USER_ID, 999, "translate")
        assert state is None

    async def test_invalid_quiz_type(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        with pytest.raises(ValueError, match="Invalid quiz_type"):
            await upsert_sm2_state(
                db,
                USER_ID,
                word_id,
                "bogus",
                easiness_factor=2.5,
                interval=1,
                repetitions=1,
                correct_count=1,
                next_review=datetime.now(),
            )


class TestDueWords:
    async def test_new_words_prioritized(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_word(db, USER_ID, "adj", "langsam", "slow")
        due = await get_due_words(db, USER_ID, limit=7)
        assert len(due) == 2

    async def test_respects_limit(self, db):
        for i in range(10):
            await add_word(db, USER_ID, "adj", f"word{i}", f"trans{i}")
        due = await get_due_words(db, USER_ID, limit=3)
        assert len(due) == 3

    async def test_filter_by_tag(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast", tags="common")
        await add_word(db, USER_ID, "adj", "langsam", "slow", tags="rare")
        due = await get_due_words(db, USER_ID, limit=7, tag="common")
        assert len(due) == 1

    async def test_tag_with_sql_wildcards(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast", tags="a%b")
        await add_word(db, USER_ID, "adj", "langsam", "slow", tags="axb")
        due = await get_due_words(db, USER_ID, limit=7, tag="a%b")
        assert len(due) == 1


class TestQuizHistory:
    async def test_add_history(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        await add_quiz_history(db, USER_ID, word_id, "translate", False)
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM quiz_history WHERE user_id = ?",
            (USER_ID,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2

    async def test_invalid_quiz_type(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        with pytest.raises(ValueError, match="Invalid quiz_type"):
            await add_quiz_history(db, USER_ID, word_id, "bogus", True)


class TestStats:
    async def test_stats_counts(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        await add_quiz_history(db, USER_ID, word_id, "translate", True)

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["quizzes_completed"] == 2
        assert stats["words_added"] == 1
        assert stats["words_learned"] == 0

    async def _mark_learned(self, db, word_id, quiz_types):
        """Helper: add 4 correct quiz_history entries for each quiz_type."""
        for qt in quiz_types:
            for _ in range(4):
                await add_quiz_history(db, USER_ID, word_id, qt, True)

    async def test_word_learned_all_types(self, db):
        """Adjective needs translate + multiple_choice both at 4 to be learned."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice"])

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_word_not_learned_partial(self, db):
        """Adjective with only translate at 4 is NOT learned (missing multiple_choice)."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await self._mark_learned(db, word_id, ["translate"])

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 0

    async def test_noun_learned_needs_article(self, db):
        """Noun needs translate + multiple_choice + article all at 4."""
        word_id = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice", "article"])

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_noun_not_learned_missing_article(self, db):
        """Noun with translate + multiple_choice at 4 but no article is NOT learned."""
        word_id = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice"])

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 0

    async def test_irregular_verb_learned(self, db):
        """Irregular verb needs translate + multiple_choice + verb_forms."""
        word_id = await add_word(
            db,
            USER_ID,
            "v",
            "fahren",
            "to drive",
            partizip_ii="ist gefahren",
            irregular_forms={"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"},
        )
        await self._mark_learned(db, word_id, ["translate", "multiple_choice", "verb_forms"])

        since = datetime.now() - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_word_learned_old_not_in_period(self, db):
        """Word that became learned BEFORE the period should not count."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice"])
        # Backdate all quiz_history to 60 days ago
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        await db.execute(
            "UPDATE quiz_history SET answered_at = ? WHERE user_id = ?",
            (old_date, USER_ID),
        )
        await db.commit()

        # Period is "last week" \u2014 should NOT count
        since = datetime.now() - timedelta(days=7)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 0

        # Period is "all time" \u2014 SHOULD count
        epoch = datetime(1970, 1, 1)
        stats = await get_stats(db, USER_ID, epoch)
        assert stats["words_learned"] == 1


class TestGetConnection:
    async def test_successful_connection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            conn = await get_connection(db_path)
            try:
                cursor = await conn.execute("PRAGMA foreign_keys")
                row = await cursor.fetchone()
                assert row[0] == 1
            finally:
                await conn.close()

    async def test_connection_to_invalid_path(self):
        with pytest.raises(sqlite3.OperationalError):
            await get_connection("/nonexistent/dir/that/cannot/exist/db.sqlite")


class TestInitDb:
    async def test_init_creates_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            await init_db(db_path)
            conn = await get_connection(db_path)
            try:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in await cursor.fetchall()]
                assert "words" in tables
                assert "sm2_state" in tables
                assert "quiz_history" in tables
            finally:
                await conn.close()

    async def test_init_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test.db"
            await init_db(db_path)
            await init_db(db_path)

    async def test_init_invalid_path(self):
        with pytest.raises(sqlite3.OperationalError):
            await init_db("/nonexistent/dir/that/cannot/exist/db.sqlite")


class TestParseIrregularForms:
    def test_valid_json(self):
        forms = parse_irregular_forms('{"ich": "fahre", "du": "fährst"}')
        assert forms == {"ich": "fahre", "du": "fährst"}

    def test_none(self):
        assert parse_irregular_forms(None) is None

    def test_empty_string(self):
        assert parse_irregular_forms("") is None

    def test_invalid_json(self):
        assert parse_irregular_forms("not json") is None

    def test_non_dict_json(self):
        assert parse_irregular_forms('["a", "b"]') is None

    def test_integer_json(self):
        assert parse_irregular_forms("42") is None

    def test_whitespace_only(self):
        assert parse_irregular_forms("   ") is None


class TestIrregularFormsRoundTrip:
    async def test_store_and_parse(self, db):
        forms = {"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"}
        word_id = await add_word(
            db,
            USER_ID,
            "v",
            "fahren",
            "to drive",
            partizip_ii="ist gefahren",
            irregular_forms=forms,
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        parsed = parse_irregular_forms(word["irregular_forms"])
        assert parsed == forms

    async def test_empty_dict_stores_as_json(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "v",
            "machen",
            "to do",
            irregular_forms={},
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        # Empty dict is explicitly stored (not None)
        assert word["irregular_forms"] is not None
        parsed = parse_irregular_forms(word["irregular_forms"])
        assert parsed == {}

    async def test_none_forms_stores_null(self, db):
        word_id = await add_word(
            db,
            USER_ID,
            "v",
            "machen",
            "to do",
            irregular_forms=None,
        )
        word = await get_word_by_id(db, word_id, USER_ID)
        assert word["irregular_forms"] is None


class TestQuizTypesAdverb:
    def test_adverb(self):
        word = {"part_of_speech": "adv", "irregular_forms": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]


class TestFindWordsByGerman:
    async def test_find_existing(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", article="die")
        matches = await find_words_by_german(db, USER_ID, "Katze")
        assert len(matches) == 1
        assert matches[0]["german"] == "Katze"

    async def test_case_insensitive(self, db):
        await add_word(db, USER_ID, "n", "Katze", "cat", article="die")
        matches = await find_words_by_german(db, USER_ID, "katze")
        assert len(matches) == 1

    async def test_not_found(self, db):
        matches = await find_words_by_german(db, USER_ID, "Hund")
        assert len(matches) == 0

    async def test_multiple_matches(self, db):
        await add_word(db, USER_ID, "n", "Bank", "bank (seat)", article="die")
        await add_word(db, USER_ID, "n", "Bank", "bank (financial)", article="die")
        matches = await find_words_by_german(db, USER_ID, "Bank")
        assert len(matches) == 2

    async def test_user_isolation(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        matches = await find_words_by_german(db, 99999, "schnell")
        assert len(matches) == 0

    async def test_strips_whitespace(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        matches = await find_words_by_german(db, USER_ID, "  schnell  ")
        assert len(matches) == 1
