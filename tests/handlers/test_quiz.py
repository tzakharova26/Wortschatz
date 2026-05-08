"""Tests for bot/handlers/quiz.py — /quiz conversation flow plus the small
helpers used by the quiz handler (rating keyboard, answer formatter, markup
builder)."""

import bot.handlers as h
import bot.quiz as q
from bot.config import (
    QUALITY_BLACKOUT,
    QUALITY_EASY,
    QUALITY_GOOD,
    QUALITY_WRONG,
    QUIZ_MAX_SIZE,
)
from bot.database import add_quiz_history, add_word, get_sm2_state
from bot.handlers import (
    QUIZ_ANSWERING,
    QUIZ_RATING,
    ConversationHandler,
    _build_question_markup,
    _format_answer_response,
    _rating_keyboard,
    quiz_button_answer,
    quiz_cancel,
    quiz_rating,
    quiz_start,
    quiz_text_answer,
)
from bot.handlers.quiz import _finish_quiz
from bot.quiz import QuizQuestion, QuizSession, _generate_translate
from tests.helpers import graduate_word


class TestRatingKeyboard:
    def test_correct_buttons(self):
        kb = _rating_keyboard(correct=True)
        buttons = kb.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert "Good" in texts
        assert "Easy" in texts
        assert "Misspell" in texts
        assert "Blackout" not in texts
        assert "Wrong" not in texts

    def test_wrong_buttons(self):
        kb = _rating_keyboard(correct=False)
        buttons = kb.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert "Blackout" in texts
        assert "Wrong" in texts
        assert "Misspell" in texts
        assert "Good" not in texts
        assert "Easy" not in texts

    def test_correct_callback_data(self):
        kb = _rating_keyboard(correct=True)
        buttons = kb.inline_keyboard[0]
        data = [b.callback_data for b in buttons]
        assert f"rate:{QUALITY_GOOD}" in data
        assert f"rate:{QUALITY_EASY}" in data
        assert "rate:misspell" in data

    def test_wrong_callback_data(self):
        kb = _rating_keyboard(correct=False)
        buttons = kb.inline_keyboard[0]
        data = [b.callback_data for b in buttons]
        assert f"rate:{QUALITY_BLACKOUT}" in data
        assert f"rate:{QUALITY_WRONG}" in data
        assert "rate:misspell" in data


class TestFormatAnswerResponse:
    def test_correct_format(self):
        question = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        text = _format_answer_response(question, correct=True)
        assert "Correct" in text
        assert "die Katze" in text

    def test_wrong_format(self):
        question = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        text = _format_answer_response(question, correct=False)
        assert "Wrong" in text

    def test_html_escape(self):
        # Use a value that doesn't collide with the wrapper <b> tag
        question = QuizQuestion(
            word={"german": "<script>", "translation": "x", "part_of_speech": "adj"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="<script>alert(1)</script>",
        )
        text = _format_answer_response(question, correct=True)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


class TestBuildQuestionMarkup:
    def test_multiple_choice_layout(self):
        question = QuizQuestion(
            word={"german": "x", "translation": "y", "part_of_speech": "n"},
            quiz_type="multiple_choice",
            prompt="p",
            options=["a", "b", "c", "d"],
            correct_answer="a",
        )
        markup = _build_question_markup(question)
        # multiple_choice puts each option on its own row
        assert len(markup.inline_keyboard) == 4

    def test_article_layout(self):
        question = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="article",
            prompt="p",
            options=["der", "die", "das"],
            correct_answer="die",
        )
        markup = _build_question_markup(question)
        # article puts all 3 in one row
        assert len(markup.inline_keyboard) == 1
        assert len(markup.inline_keyboard[0]) == 3

    def test_translate_no_markup(self):
        question = QuizQuestion(
            word={"german": "x", "translation": "y", "part_of_speech": "adj"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="x",
        )
        assert _build_question_markup(question) is None


class TestQuizConversation:
    async def test_quiz_start_no_words(self, fake_update, fake_context):
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No words to quiz" in text
        # Empty vocabulary → suggest /add (not /learn).
        assert "/add" in text
        assert "/learn" not in text

    async def test_quiz_start_with_words(self, fake_update, fake_context, db):
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)  # /quiz only sees graduated words
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == QUIZ_ANSWERING
        assert "quiz_session" in fake_context.user_data

    async def test_quiz_skips_brand_new_words(self, fake_update, fake_context, db):
        """A word with no quiz_history is in /learn pool, not /quiz."""
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No words to quiz" in text
        # Has un-graduated words — should point at /learn, not /add.
        assert "/learn" in text
        assert "/add" not in text

    async def test_text_answer_no_session(self, fake_update, fake_context):
        upd = fake_update(text="Katze")
        result = await quiz_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No active quiz" in text

    async def test_full_quiz_flow_persists_sm2(self, fake_update, fake_context, db):
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        upd = fake_update()
        await quiz_start(upd, fake_context)

        # Force the quiz session to have just one translate question
        # (it was generated via build_quiz_session — could be anything)
        session = fake_context.user_data["quiz_session"]
        # Trim to 1 question for predictable test
        session.questions = session.questions[:1]
        question = session.questions[0]
        # Force quiz_type translate so we can answer with text
        if question.quiz_type != "translate":
            session.questions[0] = _generate_translate(question.word)
        question = session.questions[0]

        # Send answer
        upd_text = fake_update(text=question.correct_answer)
        await quiz_text_answer(upd_text, fake_context)

        # Send rating
        upd_rate = fake_update(callback_data="rate:4")
        result = await quiz_rating(upd_rate, fake_context)
        assert result == ConversationHandler.END

        # Verify SM-2 was persisted (graduate_word seeded correct_count=1, then
        # one more correct answer makes it 2). The intent is just that the rating
        # round-tripped to the DB.
        state = await get_sm2_state(db, 12345, word_id, question.quiz_type)
        assert state is not None
        assert state["correct_count"] >= 2

    async def test_quiz_cancel_no_session(self, fake_update, fake_context):
        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert text == "Quiz cancelled."

    async def test_quiz_cancel_clears_unanswered_session(self, fake_update, fake_context, db):
        """Cancelling with zero rated answers shouldn't write SM-2 state."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.user_data["quiz_session"] = QuizSession(user_id=12345, questions=[])
        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        assert "quiz_session" not in fake_context.user_data
        # Nothing got persisted
        assert await get_sm2_state(db, 12345, word_id, "translate") is None

    async def test_quiz_cancel_persists_partial_progress(self, fake_update, fake_context, db):
        """Cancelling mid-quiz must write SM-2 + history for already-rated answers."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        word = {
            "id": word_id,
            "user_id": 12345,
            "part_of_speech": "adj",
            "german": "schnell",
            "translation": "fast",
            "article": None,
            "plural": None,
            "partizip_ii": None,
            "irregular_forms": None,
        }
        question = _generate_translate(word)
        # One question, already answered + rated as Good (4)
        session = QuizSession(
            user_id=12345,
            questions=[question],
            current_index=1,
            results=[(4, True)],
        )
        fake_context.user_data["quiz_session"] = session

        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        # SM-2 was persisted for the rated answer
        state = await get_sm2_state(db, 12345, word_id, "translate")
        assert state is not None
        assert state["correct_count"] == 1
        # User-facing message mentions partial progress + summary
        text = upd.message.reply_text.call_args.args[0]
        assert "Partial progress saved" in text
        assert "1/1 correct" in text

    async def test_quiz_start_clears_stale_state(self, fake_update, fake_context, db):
        """Re-entering /quiz should clear any stale session state from a previous run."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        # Pretend a previous session was abandoned
        fake_context.user_data["quiz_session"] = "stale-session"
        fake_context.user_data["quiz_all_words"] = [{"stale": True}]
        fake_context.user_data["last_answer_correct"] = True

        upd = fake_update()
        await quiz_start(upd, fake_context)
        # Stale state must be replaced
        assert fake_context.user_data["quiz_session"] != "stale-session"
        assert fake_context.user_data["quiz_all_words"] != [{"stale": True}]

    async def test_quiz_size_arg(self, fake_update, fake_context, db):
        """`/quiz 5` with 1 word in vocab cycles to 5 questions."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        fake_context.args = ["5"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 5

    async def test_quiz_size_and_tag(self, fake_update, fake_context, db):
        """`/quiz 3 animals` filters by tag and uses requested size."""
        w1 = await add_word(db, 12345, "adj", "schnell", "fast", tags="animals")
        w2 = await add_word(db, 12345, "adj", "langsam", "slow", tags="other")
        await graduate_word(db, w1)
        await graduate_word(db, w2)
        fake_context.args = ["3", "animals"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 3
        # Only words tagged "animals" should appear
        assert all(q.word["german"] == "schnell" for q in session.questions)

    async def test_quiz_args_order_independent(self, fake_update, fake_context, db):
        """`/quiz animals 3` parses the same as `/quiz 3 animals`."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast", tags="animals")
        await graduate_word(db, word_id)
        fake_context.args = ["animals", "3"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 3

    async def test_quiz_size_capped(self, fake_update, fake_context, db):
        """Requested size above QUIZ_MAX_SIZE is capped, with a notice in the start message."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        fake_context.args = [str(QUIZ_MAX_SIZE + 100)]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == QUIZ_MAX_SIZE
        # Start message should mention the cap
        first_call_text = upd.message.reply_text.call_args_list[0].args[0]
        assert "Capped" in first_call_text

    async def test_quiz_zero_size_rejected(self, fake_update, fake_context, db):
        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = ["0"]
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "positive" in text.lower()

    async def test_quiz_repeat_notice_when_vocab_smaller(self, fake_update, fake_context, db):
        """Start message tells the user words will repeat when vocab < size."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        fake_context.args = ["10"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        first_call_text = upd.message.reply_text.call_args_list[0].args[0]
        assert "repeat" in first_call_text.lower()

    async def test_text_answer_when_session_finished(self, fake_update, fake_context, db):
        session = QuizSession(user_id=12345, questions=[])
        fake_context.user_data["quiz_session"] = session
        upd = fake_update(text="something")
        result = await quiz_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No active quiz" in text

    async def test_misspell_callback_repeats_word(self, fake_update, fake_context, db):
        """Tapping Misspell records None in results and adds the word again."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        session.questions = session.questions[:1]
        # Force translate quiz_type
        session.questions[0] = _generate_translate(session.questions[0].word)
        original_q_count = len(session.questions)

        # Answer (correctly so we get the right rating buttons)
        upd_text = fake_update(text="schnell")
        await quiz_text_answer(upd_text, fake_context)

        # Tap Misspell
        upd_rate = fake_update(callback_data="rate:misspell")
        result = await quiz_rating(upd_rate, fake_context)

        # Misspell should add a new question
        assert len(session.questions) == original_q_count + 1
        # results has None placeholder (not a tuple)
        assert session.results == [None]
        # Session is not finished — there's still the appended question
        assert result == QUIZ_ANSWERING

    async def test_button_answer_multiple_choice_correct(self, fake_update, fake_context, db):
        """Tapping the correct multiple-choice option transitions to QUIZ_RATING."""
        word = {
            "id": 1,
            "part_of_speech": "n",
            "german": "Katze",
            "article": "die",
            "plural": "Katzen",
            "partizip_ii": None,
            "irregular_forms": None,
            "translation": "cat",
            "tags": "",
            "user_id": 12345,
        }
        question = QuizQuestion(
            word=word,
            quiz_type="multiple_choice",
            prompt="What does 'die Katze' mean?",
            options=["cat", "dog", "mouse", "bird"],
            correct_answer="cat",
        )
        session = QuizSession(user_id=12345, questions=[question])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="mc:cat")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is True
        # Edit text should mention "Correct"
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Correct" in text

    async def test_button_answer_multiple_choice_wrong(self, fake_update, fake_context, db):
        word = {
            "id": 1,
            "part_of_speech": "n",
            "german": "Katze",
            "article": "die",
            "plural": "Katzen",
            "partizip_ii": None,
            "irregular_forms": None,
            "translation": "cat",
            "tags": "",
            "user_id": 12345,
        }
        question = QuizQuestion(
            word=word,
            quiz_type="multiple_choice",
            prompt="What does 'die Katze' mean?",
            options=["cat", "dog", "mouse", "bird"],
            correct_answer="cat",
        )
        session = QuizSession(user_id=12345, questions=[question])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="mc:dog")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is False
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Wrong" in text

    async def test_button_answer_article(self, fake_update, fake_context, db):
        word = {
            "id": 1,
            "part_of_speech": "n",
            "german": "Katze",
            "article": "die",
            "plural": "Katzen",
            "partizip_ii": None,
            "irregular_forms": None,
            "translation": "cat",
            "tags": "",
            "user_id": 12345,
        }
        question = QuizQuestion(
            word=word,
            quiz_type="article",
            prompt="What is the article for 'Katze'?",
            options=["der", "die", "das"],
            correct_answer="die",
        )
        session = QuizSession(user_id=12345, questions=[question])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="art:die")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is True

    async def test_button_answer_no_session(self, fake_update, fake_context, db):
        upd = fake_update(callback_data="mc:something")
        result = await quiz_button_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "No active quiz" in text


class TestFinishQuizPartialFailure:
    async def test_one_word_fails_others_succeed(self, fake_update, fake_context, db, monkeypatch):
        """If one upsert raises, the summary still includes a note about failures.

        Build the session by hand so the test deterministically exercises the
        2-word failure branch — relying on quiz_start could give us a 1-word
        session (cycling) and silently skip the assertion.
        """
        wid1 = await add_word(db, 12345, "adj", "schnell", "fast")
        wid2 = await add_word(db, 12345, "adj", "langsam", "slow")
        await graduate_word(db, wid1)
        await graduate_word(db, wid2)

        # Build the QuizSession explicitly with two translate questions and
        # both already marked answered+rated — no reliance on randomness.
        word1 = {
            "id": wid1,
            "user_id": 12345,
            "part_of_speech": "adj",
            "german": "schnell",
            "translation": "fast",
            "article": None,
            "plural": None,
            "partizip_ii": None,
            "irregular_forms": None,
        }
        word2 = {
            "id": wid2,
            "user_id": 12345,
            "part_of_speech": "adj",
            "german": "langsam",
            "translation": "slow",
            "article": None,
            "plural": None,
            "partizip_ii": None,
            "irregular_forms": None,
        }
        questions = [_generate_translate(word1), _generate_translate(word2)]
        session = QuizSession(
            user_id=12345,
            questions=questions,
            current_index=2,
            results=[(4, True), (4, True)],
        )
        fake_context.user_data["quiz_session"] = session

        # Patch upsert_sm2_state in bot.quiz (where apply_results uses it)
        original = q.upsert_sm2_state

        async def failing_upsert(conn, user_id, word_id, *args, **kwargs):
            if word_id == wid1:
                raise RuntimeError("simulated failure")
            return await original(conn, user_id, word_id, *args, **kwargs)

        monkeypatch.setattr(q, "upsert_sm2_state", failing_upsert)

        fake_query = fake_update(callback_data="rate:4")
        result = await _finish_quiz(fake_query.callback_query, fake_context)
        assert result == h.ConversationHandler.END
        # Summary mentions the failure note
        summary = fake_query.callback_query.message.reply_text.call_args.args[0]
        assert "could not be saved" in summary

        # And the surviving word's history DID advance — that's the "others succeed" half.
        cursor = await db.execute(
            "SELECT COUNT(*) FROM quiz_history WHERE user_id = ? AND word_id = ?",
            (12345, wid2),
        )
        wid2_history_count = (await cursor.fetchone())[0]
        # graduate_word seeded 1 row; apply_results adds one more for word2 (the OK one).
        assert wid2_history_count >= 2

        # Suppress unused-import lint
        _ = add_quiz_history


class TestQuizEdgeCases:
    """Smaller error/edge paths in /quiz that the main flow tests don't hit."""

    async def test_no_words_with_tag_mentions_tag(self, fake_update, fake_context, db):
        """Empty due-pool message includes the tag filter when one was given."""
        fake_context.args = ["nonexistent_tag"]
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "(tag: #nonexistent_tag)" in text

    async def test_rating_no_session(self, fake_update, fake_context):
        upd = fake_update(callback_data="rate:4")
        result = await quiz_rating(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "No active quiz" in text

    async def test_rating_invalid_quality_data(self, fake_update, fake_context):
        """Malformed rate data (not an int, not 'misspell') is logged and rejected."""
        # Build a minimal session so the rating handler doesn't bail on `not session`.
        session = QuizSession(
            user_id=12345,
            questions=[
                _generate_translate(
                    {
                        "id": 1,
                        "user_id": 12345,
                        "part_of_speech": "adj",
                        "german": "schnell",
                        "translation": "fast",
                        "article": None,
                        "plural": None,
                        "partizip_ii": None,
                        "irregular_forms": None,
                        "tags": "",
                    }
                )
            ],
        )
        fake_context.user_data["quiz_session"] = session
        fake_context.user_data["last_answer_correct"] = True
        upd = fake_update(callback_data="rate:not_a_number")
        result = await quiz_rating(upd, fake_context)
        assert result == QUIZ_RATING  # stays in rating state
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Invalid rating" in text

    async def test_quiz_cancel_partial_with_db_failure(
        self, fake_update, fake_context, db, monkeypatch
    ):
        """If apply_results reports failures during /cancel, the summary mentions them."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        word = {
            "id": word_id,
            "user_id": 12345,
            "part_of_speech": "adj",
            "german": "schnell",
            "translation": "fast",
            "article": None,
            "plural": None,
            "partizip_ii": None,
            "irregular_forms": None,
        }
        session = QuizSession(
            user_id=12345,
            questions=[_generate_translate(word)],
            current_index=1,
            results=[(4, True)],
        )
        fake_context.user_data["quiz_session"] = session

        # Patch upsert_sm2_state so apply_results reports a failure.
        original = q.upsert_sm2_state

        async def failing_upsert(conn, user_id, w_id, *args, **kwargs):
            raise RuntimeError("simulated db failure")

        monkeypatch.setattr(q, "upsert_sm2_state", failing_upsert)

        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "Partial progress saved" in text
        assert "could not be saved" in text

        # Restore for any later tests in the same module run
        monkeypatch.setattr(q, "upsert_sm2_state", original)
