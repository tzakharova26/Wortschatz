"""Tests for bot/handlers/add.py — /add conversation flow and _save_words."""

from bot.database import add_word, get_words
from bot.handlers import (
    ADD_CONFIRM,
    ADD_WORDS,
    CB_ADD,
    ConversationHandler,
    _save_words,
    add_callback,
    add_skip,
    add_start,
    add_words_received,
)


class TestAddConversation:
    async def test_add_start_no_tag(self, fake_update, fake_context):
        upd = fake_update()
        result = await add_start(upd, fake_context)
        assert result == ADD_WORDS
        assert fake_context.user_data["add_tag"] == ""
        text = upd.message.reply_text.call_args.args[0]
        assert "Send words" in text

    async def test_add_start_with_tag(self, fake_update, fake_context):
        upd = fake_update()
        fake_context.args = ["animals"]
        await add_start(upd, fake_context)
        assert fake_context.user_data["add_tag"] == "animals"

    async def test_add_words_all_valid_shows_preview(self, fake_update, fake_context, db):
        """All-valid input goes to preview (ADD_CONFIRM) with Confirm/Cancel buttons,
        no DB writes yet."""
        fake_context.user_data["add_tag"] = "animals"
        upd = fake_update(text="n die Katze Katzen cat\nadj schnell fast")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_CONFIRM
        call_args = upd.message.reply_text.call_args
        text = call_args.args[0]
        assert "Preview" in text
        assert "Confirm" in text
        # The reply must include the Confirm/Cancel inline keyboard
        markup = call_args.kwargs.get("reply_markup")
        assert markup is not None
        callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
        assert f"{CB_ADD}confirm" in callbacks
        assert f"{CB_ADD}cancel" in callbacks
        # Nothing saved yet
        assert len(await get_words(db, 12345)) == 0
        assert len(fake_context.user_data["parsed_words"]) == 2

    async def test_add_callback_confirm_saves(self, fake_update, fake_context, db):
        """Tapping Confirm in the preview persists the parsed words."""
        fake_context.user_data["add_tag"] = "animals"
        fake_context.user_data["parsed_words"] = [
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
        upd = fake_update(callback_data="add:confirm")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END
        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "animals"
        # Buttons must be cleared so the user can't double-confirm
        upd.callback_query.edit_message_reply_markup.assert_awaited()

    async def test_add_callback_confirm_with_no_pending(self, fake_update, fake_context, db):
        upd = fake_update(callback_data="add:confirm")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "Nothing to save" in text

    async def test_add_words_replaces_preview(self, fake_update, fake_context, db):
        """Sending more words while in ADD_CONFIRM replaces the previewed batch."""
        fake_context.user_data["add_tag"] = ""
        fake_context.user_data["parsed_words"] = [{"old": True}]
        upd = fake_update(text="adj schnell fast")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_CONFIRM
        # Previous parsed_words was replaced
        parsed = fake_context.user_data["parsed_words"]
        assert len(parsed) == 1
        assert parsed[0]["german"] == "schnell"

    async def test_add_words_with_errors_stays_in_state(self, fake_update, fake_context, db):
        fake_context.user_data["add_tag"] = ""
        upd = fake_update(text="n die Katze Katzen cat\nbogus line\nadj schnell fast")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_WORDS
        assert fake_context.user_data["parsed_words"]
        # No DB writes yet — user must /skip or fix
        assert len(await get_words(db, 12345)) == 0

    async def test_add_skip_shows_preview(self, fake_update, fake_context, db):
        """/skip (after errors) shows preview of valid lines, doesn't save yet."""
        fake_context.user_data["add_tag"] = "test"
        fake_context.user_data["parsed_words"] = [
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
        result = await add_skip(upd, fake_context)
        assert result == ADD_CONFIRM
        text = upd.message.reply_text.call_args.args[0]
        assert "Preview" in text
        # Not yet saved
        assert len(await get_words(db, 12345)) == 0

    async def test_add_existing_word_with_new_tag_merges(self, fake_update, fake_context, db):
        """Re-adding the same word with a new tag merges, not duplicates."""
        # Existing word with tag "animals"
        await add_word(db, 12345, "n", "Katze", "cat", article="die", tags="animals")

        fake_context.user_data["add_tag"] = "A1"
        fake_context.user_data["parsed_words"] = [
            {
                "part_of_speech": "n",
                "german": "Katze",
                "translation": "cat",
                "article": "die",
                "plural": "Katzen",
                "partizip_ii": None,
                "irregular_forms": None,
            }
        ]
        upd = fake_update(callback_data="add:confirm")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END

        # No duplicate row created; tags merged
        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "animals,A1"

        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "Tag" in text and "#A1" in text

    async def test_add_existing_word_same_tag_no_change(self, fake_update, fake_context, db):
        await add_word(db, 12345, "adj", "schnell", "fast", tags="speed")

        fake_context.user_data["add_tag"] = "speed"
        fake_context.user_data["parsed_words"] = [
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
        upd = fake_update(callback_data="add:confirm")
        await add_callback(upd, fake_context)

        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "speed"

        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "Already existed" in text

    async def test_homograph_different_pos_creates_new_row(self, fake_update, fake_context, db):
        """'laut' as adj (loud) and as noun (sound) are different words."""
        await add_word(db, 12345, "adj", "laut", "loud")

        fake_context.user_data["add_tag"] = ""
        fake_context.user_data["parsed_words"] = [
            {
                "part_of_speech": "n",
                "german": "Laut",
                "translation": "sound",
                "article": "der",
                "plural": "Laute",
                "partizip_ii": None,
                "irregular_forms": None,
            }
        ]
        upd = fake_update(callback_data="add:confirm")
        await add_callback(upd, fake_context)

        words = await get_words(db, 12345)
        assert len(words) == 2  # both adj and noun rows

    async def test_add_callback_cancel_clears_state(self, fake_update, fake_context):
        fake_context.user_data["parsed_words"] = [{"x": 1}]
        fake_context.user_data["add_tag"] = "tag"
        upd = fake_update(callback_data="add:cancel")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END
        assert "parsed_words" not in fake_context.user_data
        assert "add_tag" not in fake_context.user_data
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "cancelled" in text.lower()


class TestSaveWordsValueError:
    async def test_value_error_caught_and_reported(self, fake_update, fake_context, db):
        """If add_word raises ValueError, _save_words should report it without crashing."""
        # Empty translation triggers ValueError
        parsed = [
            {
                "part_of_speech": "adj",
                "german": "schnell",
                "translation": "",  # invalid
                "article": None,
                "plural": None,
                "partizip_ii": None,
                "irregular_forms": None,
            }
        ]
        upd = fake_update()
        await _save_words(upd, fake_context, parsed, db, 12345, tag="")
        # Should have replied with an error message
        calls = upd.message.reply_text.await_args_list
        error_messages = [c.args[0] for c in calls]
        assert any("Error" in m for m in error_messages)


class TestAddEmptyInput:
    async def test_empty_text_no_words(self, fake_update, fake_context, db):
        fake_context.user_data["add_tag"] = ""
        upd = fake_update(text="\n\n   \n")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_WORDS
        text = upd.message.reply_text.call_args.args[0]
        assert "No valid words" in text


class TestAddStartClearsStale:
    async def test_clears_stale_state(self, fake_update, fake_context):
        fake_context.user_data["parsed_words"] = [{"old": True}]
        fake_context.user_data["add_tag"] = "old_tag"
        upd = fake_update()
        await add_start(upd, fake_context)
        # parsed_words must be cleared; add_tag is overwritten with the new value
        assert "parsed_words" not in fake_context.user_data
        assert fake_context.user_data["add_tag"] == ""


class TestAddErrorAndSkipBranches:
    """Smaller branches of /add that the main flow tests don't hit."""

    async def test_errors_only_no_skip_hint(self, fake_update, fake_context, db):
        """All-bad input shows 'Fix errors and resend' without the /skip option."""
        fake_context.user_data["add_tag"] = ""
        upd = fake_update(text="totally bogus line\nanother bad one")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_WORDS
        text = upd.message.reply_text.call_args.args[0]
        assert "Errors found" in text
        # No /skip option offered when there are no valid lines to skip TO.
        assert "/skip" not in text

    async def test_skip_with_no_parsed(self, fake_update, fake_context):
        """/skip with nothing parsed warns the user instead of advancing."""
        fake_context.user_data["parsed_words"] = []
        upd = fake_update()
        result = await add_skip(upd, fake_context)
        assert result == ADD_WORDS
        text = upd.message.reply_text.call_args.args[0]
        assert "No valid words" in text

    async def test_save_words_handles_generic_db_exception(
        self, fake_update, fake_context, db, monkeypatch
    ):
        """Non-ValueError DB failure (e.g. OperationalError) is caught with a different message."""
        import bot.handlers.add as add_module

        async def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(add_module, "add_word", boom)
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
        from bot.handlers import _save_words

        await _save_words(upd, fake_context, parsed, db, 12345, tag="")
        # The DB-error reply is on effective_message (matches the source path).
        replies = [c.args[0] for c in upd.effective_message.reply_text.await_args_list]
        assert any("Database error" in r for r in replies)
