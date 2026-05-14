import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from bot.database import (
    add_quiz_history,
    add_word,
    delete_word,
    find_word_by_german_pos,
    find_words_by_german,
    get_connection,
    get_due_words,
    get_learning_overview,
    get_quiz_types_for_word,
    get_sm2_state,
    get_stats,
    get_tags,
    get_word_by_id,
    get_words,
    get_words_by_pos,
    init_db,
    merge_tag,
    parse_irregular_forms,
    update_word_tags,
    upsert_sm2_state,
)

USER_ID = 12345


class TestMigration:
    async def test_init_db_adds_last_quality_to_legacy_schema(self, tmp_path):
        """init_db should add last_quality to a pre-existing sm2_state table
        that doesn't have it yet (idempotent ALTER TABLE)."""
        db_path = str(tmp_path / "legacy.db")
        # Build a sm2_state without last_quality (legacy shape)
        legacy_conn = sqlite3.connect(db_path)
        legacy_conn.executescript(
            """
            CREATE TABLE sm2_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                quiz_type TEXT NOT NULL,
                easiness_factor REAL DEFAULT 2.5,
                interval INTEGER DEFAULT 0,
                repetitions INTEGER DEFAULT 0,
                correct_count INTEGER DEFAULT 0,
                next_review TIMESTAMP,
                UNIQUE(user_id, word_id, quiz_type)
            );
            """
        )
        legacy_conn.commit()
        legacy_conn.close()

        await init_db(db_path)

        check = sqlite3.connect(db_path)
        cur = check.execute("PRAGMA table_info(sm2_state)")
        cols = {row[1] for row in cur.fetchall()}
        check.close()
        assert "last_quality" in cols


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
        word = {"part_of_speech": "v", "irregular_forms": None, "partizip_ii": "hat gemacht"}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice", "partizip"]

    def test_irregular_verb(self):
        word = {
            "part_of_speech": "v",
            "irregular_forms": '{"ich": "fahre"}',
            "partizip_ii": "ist gefahren",
        }
        assert get_quiz_types_for_word(word) == [
            "translate",
            "multiple_choice",
            "partizip",
            "verb_forms",
        ]

    def test_adjective(self):
        word = {"part_of_speech": "adj", "irregular_forms": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]

    def test_verb_with_empty_json_forms(self):
        word = {"part_of_speech": "v", "irregular_forms": "{}", "partizip_ii": None}
        assert get_quiz_types_for_word(word) == ["translate", "multiple_choice"]

    def test_verb_with_invalid_json_forms(self):
        word = {"part_of_speech": "v", "irregular_forms": "not json", "partizip_ii": None}
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
    async def test_graduated_words_returned(self, db):
        from tests.helpers import graduate_word

        w1 = await add_word(db, USER_ID, "adj", "schnell", "fast")
        w2 = await add_word(db, USER_ID, "adj", "langsam", "slow")
        await graduate_word(db, w1, USER_ID)
        await graduate_word(db, w2, USER_ID)
        due = await get_due_words(db, USER_ID, limit=7)
        assert len(due) == 2

    async def test_excludes_brand_new_words(self, db):
        """Words with no quiz_history belong to /learn, not /quiz."""
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_word(db, USER_ID, "adj", "langsam", "slow")
        due = await get_due_words(db, USER_ID, limit=7)
        assert due == []

    async def test_excludes_blackout_flagged_words(self, db):
        """A word with last_quality=0 has been demoted to /learn until graduated."""
        from tests.helpers import graduate_word

        w_ok = await add_word(db, USER_ID, "adj", "schnell", "fast")
        w_bad = await add_word(db, USER_ID, "adj", "langsam", "slow")
        await graduate_word(db, w_ok, USER_ID)
        # graduate then mark as Blackout (last_quality=0)
        await graduate_word(db, w_bad, USER_ID)
        await upsert_sm2_state(
            db,
            USER_ID,
            w_bad,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=0,
            correct_count=1,
            next_review=datetime.now() - timedelta(days=1),
            last_quality=0,
        )
        due = await get_due_words(db, USER_ID, limit=7)
        ids = [d["id"] for d in due]
        assert w_ok in ids
        assert w_bad not in ids

    async def test_excludes_words_scheduled_for_future(self, db):
        """SM-2 next_review is a real due filter, not just sort metadata."""
        due_word = await add_word(db, USER_ID, "adj", "schnell", "fast")
        future_word = await add_word(db, USER_ID, "adj", "langsam", "slow")
        now = datetime(2026, 5, 14, 12, 0)

        for wid, next_review in (
            (due_word, now - timedelta(days=1)),
            (future_word, now + timedelta(days=1)),
        ):
            await add_quiz_history(db, USER_ID, wid, "translate", True)
            await upsert_sm2_state(
                db,
                USER_ID,
                wid,
                "translate",
                easiness_factor=2.5,
                interval=1,
                repetitions=1,
                correct_count=1,
                next_review=next_review,
                last_quality=4,
            )

        due = await get_due_words(db, USER_ID, limit=7, now=now)
        assert [w["id"] for w in due] == [due_word]
        assert due[0]["earliest_review"] == (now - timedelta(days=1)).isoformat()

    async def test_respects_limit(self, db):
        from tests.helpers import graduate_word

        for i in range(10):
            wid = await add_word(db, USER_ID, "adj", f"word{i}", f"trans{i}")
            await graduate_word(db, wid, USER_ID)
        due = await get_due_words(db, USER_ID, limit=3)
        assert len(due) == 3

    async def test_filter_by_tag(self, db):
        from tests.helpers import graduate_word

        w1 = await add_word(db, USER_ID, "adj", "schnell", "fast", tags="common")
        w2 = await add_word(db, USER_ID, "adj", "langsam", "slow", tags="rare")
        await graduate_word(db, w1, USER_ID)
        await graduate_word(db, w2, USER_ID)
        due = await get_due_words(db, USER_ID, limit=7, tag="common")
        assert len(due) == 1

    async def test_tag_with_sql_wildcards(self, db):
        from tests.helpers import graduate_word

        w1 = await add_word(db, USER_ID, "adj", "schnell", "fast", tags="a%b")
        w2 = await add_word(db, USER_ID, "adj", "langsam", "slow", tags="axb")
        await graduate_word(db, w1, USER_ID)
        await graduate_word(db, w2, USER_ID)
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
    async def test_naive_datetime_rejected(self, db):
        """get_stats must refuse naive datetime — silent UTC/local confusion previously
        caused 'Today' stats to show wrong totals in Docker (TZ=UTC) vs host."""
        with pytest.raises(ValueError, match="timezone-aware"):
            await get_stats(db, USER_ID, datetime.now())

    async def test_stats_counts(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        await add_quiz_history(db, USER_ID, word_id, "translate", True)

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["quizzes_completed"] == 2
        assert stats["words_added"] == 1
        assert stats["words_learned"] == 0

    async def _mark_learned(self, db, word_id, quiz_types):
        """Helper: add 4 correct quiz_history entries for each quiz_type."""
        for qt in quiz_types:
            for _ in range(4):
                await add_quiz_history(db, USER_ID, word_id, qt, True, source="learn")

    async def test_word_learned_all_types(self, db):
        """A word counts as learned when it first graduates into quiz_history."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_word_not_learned_partial(self, db):
        """Stats learned tracks /learn graduation, not mastery of all quiz types."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await self._mark_learned(db, word_id, ["translate"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_noun_learned_needs_all_types(self, db):
        """Noun graduation counts once, even though graduation writes all quiz types."""
        word_id = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice", "article", "plural"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_noun_not_learned_missing_article(self, db):
        """A graduated noun counts even if later mastery of article is incomplete."""
        word_id = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_noun_not_learned_missing_plural(self, db):
        """Stats learned is based on graduation, not the plural mastery threshold."""
        word_id = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice", "article"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

    async def test_noun_no_plural_skips_plural_requirement(self, db):
        """Noun without a plural (e.g. 'Milch') only needs translate + MC + article."""
        word_id = await add_word(db, USER_ID, "n", "Milch", "milk", article="die", plural="")
        await self._mark_learned(db, word_id, ["translate", "multiple_choice", "article"])

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 1

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

        since = datetime.now(timezone.utc) - timedelta(days=1)
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
        since = datetime.now(timezone.utc) - timedelta(days=7)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 0

        # Period is "all time" — SHOULD count
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        stats = await get_stats(db, USER_ID, epoch)
        assert stats["words_learned"] == 1


class TestLearningOverview:
    async def test_counts_due_review_and_needs_learning(self, db):
        due_word = await add_word(db, USER_ID, "adj", "schnell", "fast")
        future_word = await add_word(db, USER_ID, "adj", "langsam", "slow")
        await add_word(db, USER_ID, "adj", "neu", "new")

        now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
        await add_quiz_history(db, USER_ID, due_word, "translate", True)
        await upsert_sm2_state(
            db,
            USER_ID,
            due_word,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=now - timedelta(days=1),
            last_quality=4,
        )
        await add_quiz_history(db, USER_ID, future_word, "translate", True)
        await upsert_sm2_state(
            db,
            USER_ID,
            future_word,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=now + timedelta(days=1),
            last_quality=4,
        )

        overview = await get_learning_overview(db, USER_ID, now=now)
        assert overview == {
            "total_words": 3,
            "needs_learning": 1,
            "review_words": 2,
            "due_review": 1,
        }

    async def test_sm2_without_history_is_not_learned(self, db):
        """SM-2 rows alone do not mark graduation; /learn writes quiz_history."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        next_review = datetime.now(timezone.utc)
        for qt in ("translate", "multiple_choice"):
            await upsert_sm2_state(
                db,
                USER_ID,
                word_id,
                qt,
                easiness_factor=2.5,
                interval=6,
                repetitions=4,
                correct_count=4,
                next_review=next_review,
                last_quality=4,
            )

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        stats = await get_stats(db, USER_ID, epoch)
        assert stats["words_learned"] == 0

    async def test_blackout_word_not_counted_as_currently_learned(self, db):
        """A Blackout-demoted word returns to /learn and drops out of learned stats."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        await upsert_sm2_state(
            db,
            USER_ID,
            word_id,
            "translate",
            easiness_factor=2.5,
            interval=0,
            repetitions=0,
            correct_count=1,
            next_review=datetime.now(timezone.utc),
            last_quality=0,
        )

        since = datetime.now(timezone.utc) - timedelta(days=1)
        stats = await get_stats(db, USER_ID, since)
        assert stats["words_learned"] == 0


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

    def test_preposition(self):
        word = {"part_of_speech": "prep", "irregular_forms": None}
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


class TestMergeTag:
    def test_add_to_empty(self):
        merged, changed = merge_tag("", "animals")
        assert merged == "animals"
        assert changed is True

    def test_add_to_existing(self):
        merged, changed = merge_tag("animals,A1", "B2")
        assert merged == "animals,A1,B2"
        assert changed is True

    def test_duplicate_no_change(self):
        merged, changed = merge_tag("animals,A1", "animals")
        assert merged == "animals,A1"
        assert changed is False

    def test_empty_new_tag_no_change(self):
        merged, changed = merge_tag("animals", "")
        assert merged == "animals"
        assert changed is False

    def test_whitespace_only_no_change(self):
        merged, changed = merge_tag("animals", "   ")
        assert merged == "animals"
        assert changed is False

    def test_strips_new_tag(self):
        merged, changed = merge_tag("animals", "  food  ")
        assert merged == "animals,food"
        assert changed is True


class TestFindWordByGermanPos:
    async def test_match_same_pos(self, db):
        wid = await add_word(db, USER_ID, "n", "Bank", "seat", article="die")
        await add_word(db, USER_ID, "n", "Hund", "dog", article="der")
        match = await find_word_by_german_pos(db, USER_ID, "Bank", "n")
        assert match is not None
        assert match["id"] == wid

    async def test_different_pos_not_match(self, db):
        await add_word(db, USER_ID, "n", "laut", "noise", article="der")
        match = await find_word_by_german_pos(db, USER_ID, "laut", "adj")
        assert match is None

    async def test_case_insensitive(self, db):
        await add_word(db, USER_ID, "adj", "Schnell", "fast")
        match = await find_word_by_german_pos(db, USER_ID, "schnell", "adj")
        assert match is not None

    async def test_user_isolation(self, db):
        await add_word(db, USER_ID, "adj", "schnell", "fast")
        match = await find_word_by_german_pos(db, 99999, "schnell", "adj")
        assert match is None


class TestUpdateWordTags:
    async def test_replaces_tags(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast", tags="old")
        await update_word_tags(db, USER_ID, wid, "new1,new2")
        word = await get_word_by_id(db, wid, USER_ID)
        assert word["tags"] == "new1,new2"

    async def test_user_isolation(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast", tags="orig")
        await update_word_tags(db, 99999, wid, "hacked")
        word = await get_word_by_id(db, wid, USER_ID)
        assert word["tags"] == "orig"
