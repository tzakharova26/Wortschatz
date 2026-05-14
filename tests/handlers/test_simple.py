"""Tests for bot/handlers/simple.py — start, help, list, tags, delete,
delete_confirm, stats, error_handler, plus the help/start text constants."""

import logging

from bot.config import LIST_MAX_WORDS
from bot.database import add_word, get_words
from bot.handlers import (
    ADD_FORMAT_MESSAGE,
    COMMANDS_HELP,
    START_MESSAGE,
    delete_command,
    delete_confirm_command,
    error_handler,
    health_command,
    help_callback,
    help_command,
    language_callback,
    list_command,
    start_command,
    stats_command,
    tags_command,
)


class TestConstants:
    def test_add_format_message_has_all_pos(self):
        assert "n article word plural translation" in ADD_FORMAT_MESSAGE
        assert "v infinitive partizip_ii translation" in ADD_FORMAT_MESSAGE
        assert "vi infinitive" in ADD_FORMAT_MESSAGE
        assert "adj word translation" in ADD_FORMAT_MESSAGE
        assert "adv word translation" in ADD_FORMAT_MESSAGE
        # Preview now uses inline buttons (Confirm + Cancel) instead of /confirm and /cancel
        assert "Confirm" in ADD_FORMAT_MESSAGE
        assert "Cancel" in ADD_FORMAT_MESSAGE

    def test_start_message_has_all_commands(self):
        for cmd in (
            "/add",
            "/list",
            "/tags",
            "/delete",
            "/quiz",
            "/stats",
            "/health",
            "/help",
            "/contact",
        ):
            assert cmd in START_MESSAGE
        # Should also explain rating buttons (via QUIZ_START_MESSAGE)
        assert "Misspell" in START_MESSAGE

    def test_commands_help_escapes_angle_brackets(self):
        """`<id|all>` etc. must be escaped — Telegram parses parse_mode=HTML strictly
        and rejects unknown tags, which once broke /start and the /help Commands button."""
        # The placeholder for /remindoff must be the escaped form.
        assert "&lt;id|all&gt;" in COMMANDS_HELP
        assert "<id|all>" not in COMMANDS_HELP
        assert "<id|all>" not in START_MESSAGE


class TestTagsCommand:
    async def test_no_tags(self, fake_update, fake_context):
        upd = fake_update()
        await tags_command(upd, fake_context)
        upd.message.reply_text.assert_awaited_once()
        assert "no tags" in upd.message.reply_text.call_args.args[0].lower()

    async def test_with_tags(self, fake_update, fake_context, db):
        await add_word(db, 12345, "n", "Katze", "cat", article="die", tags="animals")
        await add_word(db, 12345, "adj", "schnell", "fast", tags="speed")
        upd = fake_update()
        await tags_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "#animals" in text
        assert "#speed" in text


class TestListCommand:
    async def test_no_tag_arg(self, fake_update, fake_context):
        upd = fake_update()
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "specify a tag" in text.lower()

    async def test_no_words_for_tag(self, fake_update, fake_context):
        upd = fake_update()
        fake_context.args = ["nonexistent"]
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No words found" in text

    async def test_lists_words(self, fake_update, fake_context, db):
        await add_word(db, 12345, "n", "Katze", "cat", article="die", tags="animals")
        upd = fake_update()
        fake_context.args = ["animals"]
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Katze" in text
        assert "(1 total)" in text

    async def test_truncates_to_max(self, fake_update, fake_context, db):
        for i in range(LIST_MAX_WORDS + 5):
            await add_word(db, 12345, "adj", f"word{i}", f"trans{i}", tags="bulk")
        upd = fake_update()
        fake_context.args = ["bulk"]
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert f"({LIST_MAX_WORDS + 5} total)" in text
        assert "5 more" in text


class TestDeleteCommand:
    async def test_no_args(self, fake_update, fake_context):
        upd = fake_update()
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Usage" in text

    async def test_no_match(self, fake_update, fake_context):
        upd = fake_update()
        fake_context.args = ["Katze"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No word" in text

    async def test_single_match_deletes(self, fake_update, fake_context, db):
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        fake_context.args = ["schnell"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Deleted" in text
        assert len(await get_words(db, 12345)) == 0

    async def test_multiple_matches_pending(self, fake_update, fake_context, db):
        await add_word(db, 12345, "n", "Bank", "seat", article="die")
        await add_word(db, 12345, "n", "Bank", "financial", article="die")
        upd = fake_update()
        fake_context.args = ["Bank"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Multiple matches" in text
        assert len(fake_context.user_data["pending_delete"]) == 2

    async def test_delete_requires_exact_match(self, fake_update, fake_context, db):
        """/delete uses the literal text the user typed — no umlaut conversion.
        Matches storage policy: words are stored verbatim, so deletion must
        match verbatim too."""
        await add_word(db, 12345, "adj", "schön", "beautiful")

        # ASCII form does NOT match Unicode-stored word
        upd = fake_update()
        fake_context.args = ["schoen"]
        await delete_command(upd, fake_context)
        assert "No word" in upd.message.reply_text.call_args.args[0]
        assert len(await get_words(db, 12345)) == 1

        # Exact form succeeds
        upd2 = fake_update()
        fake_context.args = ["schön"]
        await delete_command(upd2, fake_context)
        assert "Deleted" in upd2.message.reply_text.call_args.args[0]
        assert len(await get_words(db, 12345)) == 0

    async def test_clears_pending_on_new_call(self, fake_update, fake_context, db):
        fake_context.user_data["pending_delete"] = [99, 100]
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        fake_context.args = ["schnell"]
        await delete_command(upd, fake_context)
        # pending_delete must be cleared by the new /delete (single-match deletes immediately)
        assert "pending_delete" not in fake_context.user_data


class TestDeleteConfirmCommand:
    async def test_nothing_pending(self, fake_update, fake_context):
        upd = fake_update()
        await delete_confirm_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Nothing to confirm" in text

    async def test_confirms_deletion(self, fake_update, fake_context, db):
        wid1 = await add_word(db, 12345, "n", "Bank", "seat", article="die")
        wid2 = await add_word(db, 12345, "n", "Bank", "financial", article="die")
        fake_context.user_data["pending_delete"] = [wid1, wid2]
        upd = fake_update()
        await delete_confirm_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "2" in text
        assert len(await get_words(db, 12345)) == 0
        assert "pending_delete" not in fake_context.user_data

    async def test_expired_pending_delete_refused(self, fake_update, fake_context, db, monkeypatch):
        """A pending_delete past its TTL should be refused, not silently confirmed.

        Regression for the lifetime bug — previously if the user typed /delete
        Bank → got 2 matches → wandered off → ran /delete_confirm an hour later,
        the stale list was acted on without warning.
        """
        from bot.handlers import PENDING_DELETE_TTL_S, pending_set

        wid1 = await add_word(db, 12345, "n", "Bank", "seat", article="die")
        wid2 = await add_word(db, 12345, "n", "Bank", "financial", article="die")
        pending_set(fake_context, "pending_delete", [wid1, wid2], ttl=PENDING_DELETE_TTL_S)

        # Fast-forward monotonic clock past the TTL.
        from bot.handlers import _shared as shared_module

        real_monotonic = shared_module.time.monotonic
        monkeypatch.setattr(
            shared_module.time,
            "monotonic",
            lambda: real_monotonic() + PENDING_DELETE_TTL_S + 1,
        )

        upd = fake_update()
        await delete_confirm_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "expired" in text.lower()
        # Words must NOT have been deleted
        assert len(await get_words(db, 12345)) == 2


class TestStartHelp:
    async def test_start_command(self, fake_update, fake_context):
        upd = fake_update()
        await start_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Welcome" in text
        assert "Добро пожаловать" in text
        markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
        buttons = markup.inline_keyboard[0]
        assert [b.text for b in buttons] == ["English", "Русский"]
        assert [b.callback_data for b in buttons] == ["lang:start:en", "lang:start:ru"]

    async def test_start_language_callback_sets_language_and_shows_welcome(
        self, fake_update, fake_context
    ):
        upd = fake_update(callback_data="lang:start:ru")
        await language_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Привет" in text
        assert "/quiz" in text
        assert fake_context.user_data["language"] == "ru"

    async def test_help_command_shows_buttons(self, fake_update, fake_context):
        upd = fake_update()
        await help_command(upd, fake_context)
        upd.message.reply_text.assert_awaited_once()
        markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
        button_texts = [b.text for b in markup.inline_keyboard[0]]
        assert "Commands" in button_texts
        assert "How to add words" in button_texts
        assert "Learn & quiz" in button_texts
        assert "Contact owner" in button_texts


class TestHelpCallback:
    async def test_commands_topic(self, fake_update, fake_context):
        upd = fake_update(callback_data="help:commands")
        await help_callback(upd, fake_context)
        upd.callback_query.answer.assert_awaited_once()
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "/add" in text
        assert "/quiz" in text

    async def test_add_topic(self, fake_update, fake_context):
        upd = fake_update(callback_data="help:add")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert text == ADD_FORMAT_MESSAGE

    async def test_practice_topic(self, fake_update, fake_context):
        upd = fake_update(callback_data="help:practice")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        # Combined help should mention both flows and the SM-2 rating buttons
        assert "/learn" in text
        assert "/quiz" in text
        assert "Translate" in text
        assert "Multiple choice" in text
        assert "Misspell" in text

    async def test_unknown_topic(self, fake_update, fake_context):
        upd = fake_update(callback_data="help:bogus")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Unknown" in text


class TestErrorHandler:
    async def test_with_message(self, fake_update, fake_context):
        upd = fake_update()
        fake_context.error = ValueError("boom")
        await error_handler(upd, fake_context)
        text = upd.effective_message.reply_text.call_args.args[0]
        assert "Something went wrong" in text

    async def test_no_update(self, fake_context):
        fake_context.error = ValueError("boom")
        # Should not raise
        await error_handler(None, fake_context)

    async def test_logs_traceback(self, fake_update, fake_context, caplog):
        """Error handler must log with full traceback. Specifically: a record
        from ``bot.handlers.simple`` must carry ``exc_info`` whose first element
        is the actual ValueError. Loose 'or' on getMessage was almost-unfailable."""
        upd = fake_update()
        try:
            raise ValueError("boom!")
        except ValueError as e:
            fake_context.error = e
        with caplog.at_level(logging.ERROR):
            await error_handler(upd, fake_context)

        matching = [
            r
            for r in caplog.records
            if r.name == "bot.handlers.simple"
            and r.exc_info is not None
            and r.exc_info[0] is ValueError
        ]
        debug = [
            (r.name, r.levelname, r.exc_info[0] if r.exc_info else None) for r in caplog.records
        ]
        assert matching, (
            "expected an ERROR record from bot.handlers.simple with "
            f"exc_info[0] is ValueError; got {debug}"
        )


class TestStatsCommand:
    async def test_stats_command(self, fake_update, fake_context):
        upd = fake_update()
        await stats_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Statistics" in text
        assert "Today" in text
        assert "This week" in text
        assert "Overall" not in text
        upd.message.reply_photo.assert_awaited_once()


class TestHealthCommand:
    async def test_health_requires_owner_config(self, fake_update, fake_context, monkeypatch):
        monkeypatch.delenv("OWNER_USER_ID", raising=False)
        upd = fake_update()

        await health_command(upd, fake_context)

        text = upd.message.reply_text.call_args.args[0]
        assert "OWNER_USER_ID" in text

    async def test_health_rejects_non_owner(self, fake_update, fake_context, monkeypatch):
        monkeypatch.setenv("OWNER_USER_ID", "777")
        upd = fake_update(user_id=12345)

        await health_command(upd, fake_context)

        text = upd.message.reply_text.call_args.args[0]
        assert "owner" in text.lower()

    async def test_health_owner_gets_snapshot(self, fake_update, fake_context, db, monkeypatch):
        monkeypatch.setenv("OWNER_USER_ID", "12345")
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update(user_id=12345)

        await health_command(upd, fake_context)

        text = upd.message.reply_text.call_args.args[0]
        assert "Bot health" in text
        assert "Users:" in text
        assert "Words:" in text
        assert "Learning queue:" in text
