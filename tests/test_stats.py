from datetime import datetime, timedelta

from bot.database import add_quiz_history, add_word
from bot.stats import build_stats_chart_file, build_stats_chart_svg, get_user_stats

USER_ID = 12345


class TestGetUserStats:
    async def test_empty_stats(self, db):
        text = await get_user_stats(db, USER_ID)
        assert "Today" in text
        assert "This week" in text
        assert "Quizzes: 0" in text

    async def test_with_data(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)
        text = await get_user_stats(db, USER_ID)
        assert "Quizzes: 1" in text
        assert "Words added: 1" in text

    async def test_only_today_and_week_sections_present(self, db):
        text = await get_user_stats(db, USER_ID)
        assert "<b>Today:</b>" in text
        assert "<b>This week:</b>" in text
        assert "<b>This month:</b>" not in text
        assert "<b>Overall:</b>" not in text

    async def test_old_quiz_not_in_short_text_stats(self, db):
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
        # Today/week should be 0; month/year are represented by the graph.
        sections = text.split("<b>")
        today_part = next(s for s in sections if s.startswith("Today:"))
        week_part = next(s for s in sections if s.startswith("This week:"))
        assert "Quizzes: 0" in today_part
        assert "Quizzes: 0" in week_part

    async def test_words_learned_in_stats(self, db):
        """Adjective with translate + multiple_choice each having 4 correct entries = learned."""
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        for qt in ("translate", "multiple_choice"):
            for _ in range(4):
                await add_quiz_history(db, USER_ID, word_id, qt, True, source="learn")
        text = await get_user_stats(db, USER_ID)
        assert "Words learned: 1" in text

    async def test_stats_chart_svg_contains_activity_sections(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, word_id, "translate", True)

        svg = await build_stats_chart_svg(db, USER_ID, lang="en")

        assert svg.startswith("<svg")
        assert "Last 7 days" in svg
        assert "Last 30 days" in svg
        assert "Last 12 months" in svg
        assert "Review streak" in svg

    async def test_stats_chart_file_is_png_bytes(self, db):
        chart = await build_stats_chart_file(db, USER_ID, lang="ru")

        assert chart.name == "wortschatz_stats.png"
        assert chart.getvalue().startswith(b"\x89PNG")
