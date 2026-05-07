"""Shared test helpers."""

from __future__ import annotations

from datetime import datetime, timedelta


async def graduate_word(
    db,
    word_id: int,
    user_id: int = 12345,
    quiz_types: tuple[str, ...] = ("translate",),
) -> None:
    """Mark a word as already-seen so it appears in /quiz instead of /learn.

    /quiz now excludes words with no quiz_history (they belong to /learn).
    Tests that exercise /quiz flow on a freshly-added word need to seed history
    first; this helper writes one synthetic correct answer + sm2_state row per
    quiz_type with last_quality=4 (so the word is graduated, not Blackout-flagged).
    """
    from bot.database import add_quiz_history, upsert_sm2_state

    next_review = datetime.now() - timedelta(days=1)  # due
    for qt in quiz_types:
        await add_quiz_history(db, user_id, word_id, qt, correct=True)
        await upsert_sm2_state(
            db,
            user_id,
            word_id,
            qt,
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=next_review,
            last_quality=4,
        )
