from datetime import datetime, timedelta

from bot.database import add_quiz_history, add_word
from bot.stats import get_user_stats

USER_ID = 12345


class TestGetUserStats:
    async def test_empty_stats(self, db):
        text = await get_user_stats(db, USER_ID)
        assert "Today" in text
        assert "This week" in text
        assert "This month" in text
        assert "Overall" in text
        assert "Learning queue" in text
        assert "Quizzes: 0" in text

    async def test_with_data(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        text = await get_user_stats(db, USER_ID)
        assert "Quizzes: 1" in text
        assert "Words added: 1" in text

    async def test_overall_section_present(self, db):
        text = await get_user_stats(db, USER_ID)
        assert "<b>Overall:</b>" in text
        assert "<b>Today:</b>" in text
        assert "<b>This week:</b>" in text
        assert "<b>This month:</b>" in text

    async def test_old_quiz_in_overall_only(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        # Backdate the quiz history to 60 days ago
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        await db.execute(
            "UPDATE quiz_history SET answered_at = ? WHERE user_id = ?",
            (old_date, USER_ID),
        )
        await db.commit()

        text = await get_user_stats(db, USER_ID)
        # Today/Week/Month should be 0, but Overall should be 1
        # Parse sections to verify
        sections = text.split("<b>")
        # Find each section's quizzes count
        today_part = next(s for s in sections if s.startswith("Today:"))
        overall_part = next(s for s in sections if s.startswith("Overall:"))
        assert "Quizzes: 0" in today_part
        assert "Quizzes: 1" in overall_part

    async def test_words_learned_in_stats(self, db):
        """Adjective with translate + multiple_choice each having 4 correct entries = learned."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        for qt in ("translate", "multiple_choice"):
            for _ in range(4):
                await add_quiz_history(db, USER_ID, word_id, qt, True, source="learn")
        text = await get_user_stats(db, USER_ID)
        assert "Words learned: 1" in text
        assert "Ready to review" in text
        assert "Waiting to learn" in text
