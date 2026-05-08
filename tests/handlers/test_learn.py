"""Tests for bot/handlers/learn.py — /learn conversation flow and the
post-/add 'Start learning' button. (Tests for the bot.learn core module live
in tests/test_learn.py.)"""

from bot.config import LEARN_MIN_SIZE
from bot.database import (
    add_word,
    get_due_words,
    get_needs_learning_words,
)
from bot.handlers import (
    CB_LEARN_BATCH,
    LEARN_ANSWERING,
    ConversationHandler,
    _save_words,
    learn_batch_callback,
    learn_button_answer,
    learn_cancel,
    learn_start,
    learn_text_answer,
)
from bot.learn import LearnSession


class TestLearnConversation:
    async def test_learn_start_with_no_eligible_words(self, fake_update, fake_context, db):
        upd = fake_update()
        result = await learn_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "Nothing to learn" in text

    async def test_learn_start_builds_session_for_new_word(self, fake_update, fake_context, db):
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        result = await learn_start(upd, fake_context)
        assert result == LEARN_ANSWERING
        session = fake_context.user_data["learn_session"]
        # adj → 3 steps: show, mc, typed
        assert len(session.steps) == 3

    async def test_learn_size_below_minimum_is_bumped(self, fake_update, fake_context, db):
        """`/learn 2` should be bumped to LEARN_MIN_SIZE before the session is built."""
        # Seed enough words so the bump is observable
        for i in range(LEARN_MIN_SIZE + 2):
            await add_word(db, 12345, "adj", f"word{i}", f"trans{i}")

        upd = fake_update()
        fake_context.args = ["2"]
        await learn_start(upd, fake_context)

        # The "Bumped" notice should be the first reply
        first_reply = upd.message.reply_text.call_args_list[0].args[0]
        assert "Bumped" in first_reply
        # Session built with at least LEARN_MIN_SIZE words
        session = fake_context.user_data["learn_session"]
        word_ids = {step.word["id"] for step in session.steps}
        assert len(word_ids) == LEARN_MIN_SIZE

    async def test_learn_full_pass_graduates_word_into_quiz_pool(
        self, fake_update, fake_context, db
    ):
        """End-to-end: /learn a brand-new word, pass every step, then /quiz finds it."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        # Pre-/learn: word is needs-learning, /quiz pool is empty
        assert (await get_due_words(db, 12345, limit=10)) == []

        await learn_start(fake_update(), fake_context)
        session = fake_context.user_data["learn_session"]

        # Step 1: show → tap "Got it"
        await learn_button_answer(fake_update(callback_data="lshow:ok"), fake_context)
        # Step 2: MC → tap correct option
        mc_step = session.steps[1]
        correct_mc = mc_step.correct_answer
        await learn_button_answer(fake_update(callback_data=f"lmc:{correct_mc}"), fake_context)
        # Step 3: typed → send correct answer
        typed_step = session.steps[2]
        await learn_text_answer(fake_update(text=typed_step.correct_answer), fake_context)

        # Session ended — word should now be in /quiz pool
        assert "learn_session" not in fake_context.user_data
        due = await get_due_words(db, 12345, limit=10)
        assert [w["id"] for w in due] == [word_id]

    async def test_learn_failure_keeps_word_in_pool(self, fake_update, fake_context, db):
        """A wrong typed answer (twice — main + retry) leaves the word un-graduated."""
        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await learn_start(fake_update(), fake_context)
        session = fake_context.user_data["learn_session"]

        # show pass
        await learn_button_answer(fake_update(callback_data="lshow:ok"), fake_context)
        # MC pass
        await learn_button_answer(
            fake_update(callback_data=f"lmc:{session.steps[1].correct_answer}"), fake_context
        )
        # typed wrong
        await learn_text_answer(fake_update(text="wrong-answer"), fake_context)
        # retry typed: still wrong
        await learn_text_answer(fake_update(text="still-wrong"), fake_context)

        # Word stays in needs-learning, not in /quiz
        assert (await get_due_words(db, 12345, limit=10)) == []
        needs = await get_needs_learning_words(db, 12345)
        assert [w["id"] for w in needs] == [word_id]

    async def test_learn_batch_callback_uses_pending_ids(self, fake_update, fake_context, db):
        wid = await add_word(db, 12345, "adj", "schnell", "fast")
        await add_word(db, 12345, "adj", "langsam", "slow")  # not in pending list
        fake_context.user_data["pending_learn_ids"] = [wid]

        upd = fake_update(callback_data="lbatch:go")
        result = await learn_batch_callback(upd, fake_context)
        assert result == LEARN_ANSWERING
        session = fake_context.user_data["learn_session"]
        # Only the pending id should be in the session
        word_ids_in_session = {s.word["id"] for s in session.steps}
        assert word_ids_in_session == {wid}
        # Pending list is consumed
        assert "pending_learn_ids" not in fake_context.user_data

    async def test_learn_batch_callback_no_pending(self, fake_update, fake_context):
        upd = fake_update(callback_data="lbatch:go")
        result = await learn_batch_callback(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "no longer available" in text.lower()

    async def test_learn_cancel(self, fake_update, fake_context):
        fake_context.user_data["learn_session"] = LearnSession(
            user_id=12345, steps=[], required_per_word={}
        )
        upd = fake_update()
        result = await learn_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        assert "learn_session" not in fake_context.user_data

    async def test_save_words_attaches_start_learning_button(self, fake_update, fake_context, db):
        """After /add confirms with new words, the success reply has a Start learning button."""
        parsed = [
            {
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "fast",
                "article": None,
                "plural": None,
                "partizip_ii": None,
                "irregular_forms": None,
            }
        ]
        upd = fake_update()
        await _save_words(upd, fake_context, parsed, db, 12345, tag="")
        markup = upd.message.reply_text.call_args.kwargs.get("reply_markup")
        assert markup is not None
        callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert any(cb.startswith(CB_LEARN_BATCH) for cb in callbacks)
        # And the pending IDs were stashed
        assert fake_context.user_data["pending_learn_ids"]

    async def test_save_words_no_button_if_only_merges(self, fake_update, fake_context, db):
        """If every word merged into existing rows, no 'Start learning' button is offered."""
        await add_word(db, 12345, "adj", "schnell", "fast", tags="old")
        parsed = [
            {
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "fast",
                "article": None,
                "plural": None,
                "partizip_ii": None,
                "irregular_forms": None,
            }
        ]
        upd = fake_update()
        fake_context.user_data["add_tag"] = "new"
        await _save_words(upd, fake_context, parsed, db, 12345, tag="new")
        markup = upd.message.reply_text.call_args.kwargs.get("reply_markup")
        assert markup is None

    async def test_learn_zero_size_rejected(self, fake_update, fake_context, db):
        """`/learn 0` (or negative) refuses with a usage hint and ends."""
        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = ["0"]
        upd = fake_update()
        result = await learn_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "positive" in text.lower()

    async def test_learn_size_capped_to_max(self, fake_update, fake_context, db):
        """Sizes above LEARN_MAX_SIZE are clamped to the cap with a notice."""
        from bot.config import LEARN_MAX_SIZE

        for i in range(LEARN_MAX_SIZE + 5):
            await add_word(db, 12345, "adj", f"word{i}", f"trans{i}")

        fake_context.args = [str(LEARN_MAX_SIZE + 100)]
        upd = fake_update()
        await learn_start(upd, fake_context)
        first_reply = upd.message.reply_text.call_args_list[0].args[0]
        assert "Capped" in first_reply
        session = fake_context.user_data["learn_session"]
        word_ids = {step.word["id"] for step in session.steps}
        assert len(word_ids) == LEARN_MAX_SIZE

    async def test_button_answer_no_session(self, fake_update, fake_context):
        """Tapping a learn button with no active session ends the flow politely."""
        upd = fake_update(callback_data="lshow:ok")
        result = await learn_button_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "No active learning session" in text

    async def test_text_answer_no_session(self, fake_update, fake_context):
        upd = fake_update(text="anything")
        result = await learn_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No active learning session" in text

    async def test_text_during_button_only_step_nudges_user(self, fake_update, fake_context, db):
        """Typing during a SHOW (button-only) step nudges the user instead of advancing."""
        await add_word(db, 12345, "adj", "schnell", "fast")
        await learn_start(fake_update(), fake_context)
        # Before any button taps, current step is SHOW (button-only)
        upd = fake_update(text="Katze")
        result = await learn_text_answer(upd, fake_context)
        assert result == LEARN_ANSWERING
        text = upd.message.reply_text.call_args.args[0]
        assert "buttons" in text.lower()
        # Session not advanced
        session = fake_context.user_data["learn_session"]
        assert session.current_index == 0

    async def test_finish_learn_handles_db_failure(
        self, fake_update, fake_context, db, monkeypatch
    ):
        """If apply_graduations raises, the summary still includes a DB-error note."""
        import bot.learn as learn_core

        await add_word(db, 12345, "adj", "schnell", "fast")
        await learn_start(fake_update(), fake_context)

        # Pass every step so the session reaches _finish_learn with a graduation.
        await learn_button_answer(fake_update(callback_data="lshow:ok"), fake_context)
        session = fake_context.user_data["learn_session"]
        await learn_button_answer(
            fake_update(callback_data=f"lmc:{session.steps[1].correct_answer}"),
            fake_context,
        )

        # Patch apply_graduations on the core module to raise (the handler imports
        # it as ``learn_core.apply_graduations``).
        async def boom(*args, **kwargs):
            raise RuntimeError("db went away")

        monkeypatch.setattr(learn_core, "apply_graduations", boom)

        # Last step (typed) — its completion triggers _finish_learn.
        typed_step = session.steps[2]
        upd = fake_update(text=typed_step.correct_answer)
        result = await learn_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        # Summary is the LAST reply (after the per-step feedback).
        last_reply = upd.message.reply_text.call_args_list[-1].args[0]
        assert "could not be saved" in last_reply

    async def test_expired_pending_learn_ids_refused(
        self, fake_update, fake_context, db, monkeypatch
    ):
        """A pending_learn_ids past its TTL should not launch a stale /learn batch."""
        from bot.handlers import PENDING_LEARN_TTL_S, pending_set
        from bot.handlers import _shared as shared_module

        wid = await add_word(db, 12345, "adj", "schnell", "fast")
        pending_set(fake_context, "pending_learn_ids", [wid], ttl=PENDING_LEARN_TTL_S)

        real_monotonic = shared_module.time.monotonic
        monkeypatch.setattr(
            shared_module.time,
            "monotonic",
            lambda: real_monotonic() + PENDING_LEARN_TTL_S + 1,
        )

        upd = fake_update(callback_data="lbatch:go")
        result = await learn_batch_callback(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "no longer available" in text.lower()

    async def test_step_counter_grows_when_answer_wrong(self, fake_update, fake_context, db):
        """A wrong answer queues a retry; the rendered ``Step X/Y`` should
        immediately show Y incremented, even though the retry isn't appended
        to ``session.steps`` until the main run finishes."""
        # Seed a second word so the MC step has a real distractor to tap.
        # The /learn pool is filtered to a single word via word_ids.
        target = await add_word(db, 12345, "adj", "schnell", "fast")
        await add_word(db, 12345, "adj", "langsam", "slow")
        fake_context.user_data["pending_learn_ids"] = [target]
        await learn_batch_callback(fake_update(callback_data="lbatch:go"), fake_context)
        session = fake_context.user_data["learn_session"]
        assert len(session.steps) == 3  # adj → SHOW, MC, TYPED

        # Step 1: SHOW → tap "Got it" (correct). Next render shows step 2 of 3.
        upd_show = fake_update(callback_data="lshow:ok")
        await learn_button_answer(upd_show, fake_context)
        text_after_show = upd_show.callback_query.message.reply_text.call_args.args[0]
        assert "Step 2/3" in text_after_show

        # Step 2: MC → wrong → counter must show 4 because retry is queued.
        mc_step = session.steps[1]
        wrong_choice = next(o for o in mc_step.options if o != mc_step.correct_answer)
        upd_mc = fake_update(callback_data=f"lmc:{wrong_choice}")
        await learn_button_answer(upd_mc, fake_context)
        text_after_wrong = upd_mc.callback_query.message.reply_text.call_args.args[0]
        assert (
            "Step 3/4" in text_after_wrong
        ), f"Counter should grow on wrong answer; got: {text_after_wrong!r}"

    async def test_learn_cancel_persists_partial_graduation(self, fake_update, fake_context, db):
        """If a word fully graduated before cancel, its graduation must persist."""
        from bot.database import get_due_words

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await learn_start(fake_update(), fake_context)
        session = fake_context.user_data["learn_session"]

        # Fully pass the only word's three steps
        await learn_button_answer(fake_update(callback_data="lshow:ok"), fake_context)
        await learn_button_answer(
            fake_update(callback_data=f"lmc:{session.steps[1].correct_answer}"),
            fake_context,
        )
        # Inject the session back so /cancel sees graduated_words; the typed pass would
        # have ended the session naturally — we want to cancel WITH a graduated word
        # already recorded but BEFORE the auto-finish would fire. Easiest: hand-mark it.
        session.word_step_passed[word_id] = session.required_per_word[word_id]

        upd = fake_update()
        result = await learn_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "Partial progress saved" in text
        # Graduation went through to /quiz pool.
        due = await get_due_words(db, 12345, limit=10)
        assert [w["id"] for w in due] == [word_id]
