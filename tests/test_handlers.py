import json

from bot.config import QUALITY_BLACKOUT, QUALITY_EASY, QUALITY_GOOD, QUALITY_WRONG
from bot.handlers import _format_word_tables, _parse_word_line, _rating_keyboard


class TestParseWordLine:
    def test_noun(self):
        word, err = _parse_word_line("n die Katze Katzen cat")
        assert err is None
        assert word["part_of_speech"] == "n"
        assert word["article"] == "die"
        assert word["german"] == "Katze"
        assert word["plural"] == "Katzen"
        assert word["translation"] == "cat"

    def test_noun_multi_word_translation(self):
        word, err = _parse_word_line("n der Hund Hunde the dog")
        assert err is None
        assert word["translation"] == "the dog"

    def test_regular_verb(self):
        word, err = _parse_word_line("v machen hat gemacht to do")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "machen"
        assert word["partizip_ii"] == "hat gemacht"
        assert word["translation"] == "to do"
        assert word["irregular_forms"] is None

    def test_irregular_verb(self):
        word, err = _parse_word_line("vi fahren ist gefahren fahre faehrst faehrt to drive")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "fahren"
        assert word["partizip_ii"] == "ist gefahren"
        assert word["irregular_forms"] == {"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"}
        assert word["translation"] == "to drive"

    def test_regular_verb_with_long_translation_not_misparsed(self):
        """Regression: 'v gehen ist gegangen to walk on foot' must be regular."""
        word, err = _parse_word_line("v gehen ist gegangen to walk on foot")
        assert err is None
        assert word["irregular_forms"] is None
        assert word["translation"] == "to walk on foot"

    def test_irregular_verb_single_partizip(self):
        word, err = _parse_word_line("vi sehen gesehen sehe siehst sieht to see")
        assert err is None
        assert word["partizip_ii"] == "gesehen"
        assert word["irregular_forms"] == {"ich": "sehe", "du": "siehst", "er": "sieht"}
        assert word["translation"] == "to see"

    def test_irregular_verb_multi_word_translation(self):
        word, err = _parse_word_line("vi laufen ist gelaufen laufe laeufst laeuft to run very fast")
        assert err is None
        assert word["irregular_forms"] == {
            "ich": "laufe",
            "du": "l\u00e4ufst",
            "er": "l\u00e4uft",
        }
        assert word["translation"] == "to run very fast"

    def test_irregular_verb_too_few(self):
        word, err = _parse_word_line("vi fahren ist gefahren fahre")
        assert word is None
        assert err is not None

    def test_regular_verb_pipe(self):
        word, err = _parse_word_line("v | machen | hat gemacht | to do something")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "machen"
        assert word["partizip_ii"] == "hat gemacht"
        assert word["translation"] == "to do something"
        assert word["irregular_forms"] is None

    def test_regular_verb_pipe_single_partizip(self):
        word, err = _parse_word_line("v | spielen | gespielt | to play")
        assert err is None
        assert word["partizip_ii"] == "gespielt"
        assert word["translation"] == "to play"

    def test_irregular_verb_pipe(self):
        word, err = _parse_word_line(
            "vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive a car"
        )
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "fahren"
        assert word["partizip_ii"] == "ist gefahren"
        assert word["irregular_forms"] == {
            "ich": "fahre",
            "du": "fährst",
            "er": "fährt",
        }
        assert word["translation"] == "to drive a car"

    def test_regular_verb_pipe_too_few(self):
        word, err = _parse_word_line("v | machen | hat gemacht")
        assert word is None
        assert err is not None and "v |" in err

    def test_irregular_verb_pipe_too_few(self):
        word, err = _parse_word_line("vi | fahren | ist gefahren | fahre | faehrst")
        assert word is None
        assert err is not None and "vi |" in err

    def test_adjective(self):
        word, err = _parse_word_line("adj schnell fast")
        assert err is None
        assert word["part_of_speech"] == "adj"
        assert word["german"] == "schnell"
        assert word["translation"] == "fast"

    def test_adverb(self):
        word, err = _parse_word_line("adv manchmal sometimes")
        assert err is None
        assert word["part_of_speech"] == "adv"

    def test_preposition(self):
        word, err = _parse_word_line("prep mit with (+dat)")
        assert err is None
        assert word["part_of_speech"] == "prep"
        assert word["german"] == "mit"
        assert word["translation"] == "with (+dat)"

    def test_preposition_pipe(self):
        word, err = _parse_word_line("prep | wegen | because of (+gen)")
        assert err is None
        assert word["part_of_speech"] == "prep"
        assert word["german"] == "wegen"
        assert word["translation"] == "because of (+gen)"

    def test_empty_line(self):
        word, err = _parse_word_line("")
        assert word is None
        assert err is None

    def test_whitespace_line(self):
        word, err = _parse_word_line("   ")
        assert word is None
        assert err is None

    def test_too_few_parts(self):
        word, err = _parse_word_line("n Katze")
        assert word is None
        assert err is not None
        assert "Too few" in err

    def test_noun_too_few_parts(self):
        word, err = _parse_word_line("n die Katze cat")
        assert word is None
        assert "Noun needs" in err

    def test_verb_too_few_parts(self):
        word, err = _parse_word_line("v machen hat")
        assert word is None
        assert "v needs" in err

    def test_verb_ist_too_few(self):
        word, err = _parse_word_line("v fahren ist gefahren")
        assert word is None
        assert "needs more fields" in err

    def test_unknown_pos(self):
        word, err = _parse_word_line("xyz something translation")
        assert word is None
        assert "Unknown" in err

    def test_umlaut_conversion(self):
        word, err = _parse_word_line("adj schoen beautiful")
        assert err is None
        assert word["german"] == "sch\u00f6n"

    def test_verb_single_partizip(self):
        """Verb with single-word partizip (no ist/hat prefix)."""
        word, err = _parse_word_line("v spielen gespielt to play")
        assert err is None
        assert word["partizip_ii"] == "gespielt"
        assert word["translation"] == "to play"

    def test_adj_multi_word_translation(self):
        word, err = _parse_word_line("adj gut very good")
        assert err is None
        assert word["translation"] == "very good"


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
        forms = {"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"}
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
        assert "du: f\u00e4hrst" in text

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


class TestParseWordLineHtmlEscaping:
    def test_error_message_escapes_user_input(self):
        word, err = _parse_word_line("xyz <script>alert(1)</script>")
        assert word is None
        assert "<script>" not in err
        assert "&lt;" in err


class TestParseQuizArgs:
    def test_no_args(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args([]) == (None, None)

    def test_size_only(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["5"]) == (5, None)

    def test_tag_only(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["animals"]) == (None, "animals")

    def test_size_then_tag(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["5", "animals"]) == (5, "animals")

    def test_tag_then_size(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["animals", "5"]) == (5, "animals")

    def test_strips_hash(self):
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["#animals"]) == (None, "animals")

    def test_numeric_tag_eaten_as_size(self):
        """A numeric-looking tag (e.g. '5' as a tag) is interpreted as size — known limitation."""
        from bot.handlers import _parse_quiz_args

        assert _parse_quiz_args(["5"]) == (5, None)


class TestConstants:
    def test_add_format_message_has_all_pos(self):
        from bot.handlers import ADD_FORMAT_MESSAGE

        assert "n article word plural translation" in ADD_FORMAT_MESSAGE
        assert "v infinitive partizip_ii translation" in ADD_FORMAT_MESSAGE
        assert "vi infinitive" in ADD_FORMAT_MESSAGE
        assert "adj word translation" in ADD_FORMAT_MESSAGE
        assert "adv word translation" in ADD_FORMAT_MESSAGE
        assert "/cancel" in ADD_FORMAT_MESSAGE

    def test_start_message_has_all_commands(self):
        from bot.handlers import START_MESSAGE

        for cmd in ("/add", "/list", "/tags", "/delete", "/quiz", "/stats", "/help"):
            assert cmd in START_MESSAGE
        # Should also explain rating buttons (via QUIZ_START_MESSAGE)
        assert "Misspell" in START_MESSAGE


# --- Async handler tests using mocked Update/Context ---


class TestTagsCommand:
    async def test_no_tags(self, fake_update, fake_context):
        from bot.handlers import tags_command

        upd = fake_update()
        await tags_command(upd, fake_context)
        upd.message.reply_text.assert_awaited_once()
        assert "no tags" in upd.message.reply_text.call_args.args[0].lower()

    async def test_with_tags(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import tags_command

        await add_word(db, 12345, "n", "Katze", "cat", article="die", tags="animals")
        await add_word(db, 12345, "adj", "schnell", "fast", tags="speed")
        upd = fake_update()
        await tags_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "#animals" in text
        assert "#speed" in text


class TestListCommand:
    async def test_no_tag_arg(self, fake_update, fake_context):
        from bot.handlers import list_command

        upd = fake_update()
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "specify a tag" in text.lower()

    async def test_no_words_for_tag(self, fake_update, fake_context):
        from bot.handlers import list_command

        upd = fake_update()
        fake_context.args = ["nonexistent"]
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No words found" in text

    async def test_lists_words(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import list_command

        await add_word(db, 12345, "n", "Katze", "cat", article="die", tags="animals")
        upd = fake_update()
        fake_context.args = ["animals"]
        await list_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Katze" in text
        assert "(1 total)" in text

    async def test_truncates_to_max(self, fake_update, fake_context, db):
        from bot.config import LIST_MAX_WORDS
        from bot.database import add_word
        from bot.handlers import list_command

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
        from bot.handlers import delete_command

        upd = fake_update()
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Usage" in text

    async def test_no_match(self, fake_update, fake_context):
        from bot.handlers import delete_command

        upd = fake_update()
        fake_context.args = ["Katze"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No word" in text

    async def test_single_match_deletes(self, fake_update, fake_context, db):
        from bot.database import add_word, get_words
        from bot.handlers import delete_command

        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        fake_context.args = ["schnell"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Deleted" in text
        assert len(await get_words(db, 12345)) == 0

    async def test_multiple_matches_pending(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import delete_command

        await add_word(db, 12345, "n", "Bank", "seat", article="die")
        await add_word(db, 12345, "n", "Bank", "financial", article="die")
        upd = fake_update()
        fake_context.args = ["Bank"]
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Multiple matches" in text
        assert len(fake_context.user_data["pending_delete"]) == 2

    async def test_umlaut_conversion_on_delete(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import delete_command

        await add_word(db, 12345, "adj", "schön", "beautiful")
        upd = fake_update()
        fake_context.args = ["schoen"]  # ASCII form
        await delete_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Deleted" in text

    async def test_clears_pending_on_new_call(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import delete_command

        fake_context.user_data["pending_delete"] = [99, 100]
        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        fake_context.args = ["schnell"]
        await delete_command(upd, fake_context)
        # pending_delete must be cleared by the new /delete (single-match deletes immediately)
        assert "pending_delete" not in fake_context.user_data


class TestDeleteConfirmCommand:
    async def test_nothing_pending(self, fake_update, fake_context):
        from bot.handlers import delete_confirm_command

        upd = fake_update()
        await delete_confirm_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Nothing to confirm" in text

    async def test_confirms_deletion(self, fake_update, fake_context, db):
        from bot.database import add_word, get_words
        from bot.handlers import delete_confirm_command

        wid1 = await add_word(db, 12345, "n", "Bank", "seat", article="die")
        wid2 = await add_word(db, 12345, "n", "Bank", "financial", article="die")
        fake_context.user_data["pending_delete"] = [wid1, wid2]
        upd = fake_update()
        await delete_confirm_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "2" in text
        assert len(await get_words(db, 12345)) == 0
        assert "pending_delete" not in fake_context.user_data


class TestStartHelp:
    async def test_start_command(self, fake_update, fake_context):
        from bot.handlers import start_command

        upd = fake_update()
        await start_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Welcome" in text
        assert "/quiz" in text

    async def test_help_command_shows_buttons(self, fake_update, fake_context):
        from bot.handlers import help_command

        upd = fake_update()
        await help_command(upd, fake_context)
        upd.message.reply_text.assert_awaited_once()
        markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
        button_texts = [b.text for b in markup.inline_keyboard[0]]
        assert "Commands" in button_texts
        assert "How to add words" in button_texts
        assert "How quizzes work" in button_texts


class TestHelpCallback:
    async def test_commands_topic(self, fake_update, fake_context):
        from bot.handlers import help_callback

        upd = fake_update(callback_data="help:commands")
        await help_callback(upd, fake_context)
        upd.callback_query.answer.assert_awaited_once()
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "/add" in text
        assert "/quiz" in text

    async def test_add_topic(self, fake_update, fake_context):
        from bot.handlers import ADD_FORMAT_MESSAGE, help_callback

        upd = fake_update(callback_data="help:add")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert text == ADD_FORMAT_MESSAGE

    async def test_quiz_topic(self, fake_update, fake_context):
        from bot.handlers import help_callback

        upd = fake_update(callback_data="help:quiz")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Translate" in text
        assert "Multiple choice" in text
        assert "Misspell" in text

    async def test_unknown_topic(self, fake_update, fake_context):
        from bot.handlers import help_callback

        upd = fake_update(callback_data="help:bogus")
        await help_callback(upd, fake_context)
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Unknown" in text


class TestErrorHandler:
    async def test_with_message(self, fake_update, fake_context):
        from bot.handlers import error_handler

        upd = fake_update()
        fake_context.error = ValueError("boom")
        await error_handler(upd, fake_context)
        text = upd.effective_message.reply_text.call_args.args[0]
        assert "Something went wrong" in text

    async def test_no_update(self, fake_context):
        from bot.handlers import error_handler

        fake_context.error = ValueError("boom")
        # Should not raise
        await error_handler(None, fake_context)

    async def test_logs_traceback(self, fake_update, fake_context, caplog):
        """Error handler must log with full traceback (exc_info=context.error)."""
        import logging

        from bot.handlers import error_handler

        upd = fake_update()
        try:
            raise ValueError("boom!")
        except ValueError as e:
            fake_context.error = e
        with caplog.at_level(logging.ERROR):
            await error_handler(upd, fake_context)
        # caplog records should include the traceback
        assert any("ValueError" in r.getMessage() or r.exc_info for r in caplog.records)


class TestStatsCommand:
    async def test_stats_command(self, fake_update, fake_context):
        from bot.handlers import stats_command

        upd = fake_update()
        await stats_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Statistics" in text
        assert "Today" in text
        assert "Overall" in text


# --- /add conversation flow ---


class TestAddConversation:
    async def test_add_start_no_tag(self, fake_update, fake_context):
        from bot.handlers import ADD_WORDS, add_start

        upd = fake_update()
        result = await add_start(upd, fake_context)
        assert result == ADD_WORDS
        assert fake_context.user_data["add_tag"] == ""
        text = upd.message.reply_text.call_args.args[0]
        assert "Send words" in text

    async def test_add_start_with_tag(self, fake_update, fake_context):
        from bot.handlers import add_start

        upd = fake_update()
        fake_context.args = ["animals"]
        await add_start(upd, fake_context)
        assert fake_context.user_data["add_tag"] == "animals"

    async def test_add_words_all_valid_shows_preview(self, fake_update, fake_context, db):
        """All-valid input goes to preview (ADD_CONFIRM), no DB writes yet."""
        from bot.database import get_words
        from bot.handlers import ADD_CONFIRM, add_words_received

        fake_context.user_data["add_tag"] = "animals"
        upd = fake_update(text="n die Katze Katzen cat\nadj schnell fast")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_CONFIRM
        text = upd.message.reply_text.call_args.args[0]
        assert "Preview" in text
        assert "/confirm" in text
        # Nothing saved yet
        assert len(await get_words(db, 12345)) == 0
        assert len(fake_context.user_data["parsed_words"]) == 2

    async def test_add_confirm_saves(self, fake_update, fake_context, db):
        """/confirm after preview persists the parsed words."""
        from bot.database import get_words
        from bot.handlers import ConversationHandler, add_confirm

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
        upd = fake_update()
        result = await add_confirm(upd, fake_context)
        assert result == ConversationHandler.END
        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "animals"

    async def test_add_confirm_with_no_pending(self, fake_update, fake_context, db):
        from bot.handlers import ConversationHandler, add_confirm

        upd = fake_update()
        result = await add_confirm(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "Nothing to save" in text

    async def test_add_words_replaces_preview(self, fake_update, fake_context, db):
        """Sending more words while in ADD_CONFIRM replaces the previewed batch."""
        from bot.handlers import ADD_CONFIRM, add_words_received

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
        from bot.database import get_words
        from bot.handlers import ADD_WORDS, add_words_received

        fake_context.user_data["add_tag"] = ""
        upd = fake_update(text="n die Katze Katzen cat\nbogus line\nadj schnell fast")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_WORDS
        assert fake_context.user_data["parsed_words"]
        # No DB writes yet — user must /skip or fix
        assert len(await get_words(db, 12345)) == 0

    async def test_add_skip_shows_preview(self, fake_update, fake_context, db):
        """/skip (after errors) shows preview of valid lines, doesn't save yet."""
        from bot.database import get_words
        from bot.handlers import ADD_CONFIRM, add_skip

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
        from bot.database import add_word, get_words
        from bot.handlers import ConversationHandler, add_confirm

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
        upd = fake_update()
        result = await add_confirm(upd, fake_context)
        assert result == ConversationHandler.END

        # No duplicate row created; tags merged
        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "animals,A1"

        text = upd.message.reply_text.call_args.args[0]
        assert "Tag" in text and "#A1" in text

    async def test_add_existing_word_same_tag_no_change(self, fake_update, fake_context, db):
        from bot.database import add_word, get_words
        from bot.handlers import add_confirm

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
        upd = fake_update()
        await add_confirm(upd, fake_context)

        words = await get_words(db, 12345)
        assert len(words) == 1
        assert words[0]["tags"] == "speed"

        text = upd.message.reply_text.call_args.args[0]
        assert "Already existed" in text

    async def test_homograph_different_pos_creates_new_row(self, fake_update, fake_context, db):
        """'laut' as adj (loud) and as noun (sound) are different words."""
        from bot.database import add_word, get_words
        from bot.handlers import add_confirm

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
        upd = fake_update()
        await add_confirm(upd, fake_context)

        words = await get_words(db, 12345)
        assert len(words) == 2  # both adj and noun rows

    async def test_add_cancel(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, add_cancel

        fake_context.user_data["parsed_words"] = [{"x": 1}]
        upd = fake_update()
        result = await add_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        assert "parsed_words" not in fake_context.user_data


# --- /quiz conversation flow ---


class TestQuizConversation:
    async def test_quiz_start_no_words(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, quiz_start

        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No words to quiz" in text

    async def test_quiz_start_with_words(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import QUIZ_ANSWERING, quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == QUIZ_ANSWERING
        assert "quiz_session" in fake_context.user_data

    async def test_text_answer_no_session(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, quiz_text_answer

        upd = fake_update(text="Katze")
        result = await quiz_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No active quiz" in text

    async def test_full_quiz_flow_persists_sm2(self, fake_update, fake_context, db):
        from bot.database import add_word, get_sm2_state
        from bot.handlers import (
            ConversationHandler,
            quiz_rating,
            quiz_start,
            quiz_text_answer,
        )

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        await quiz_start(upd, fake_context)

        # Force the quiz session to have just one translate question
        # (it was generated via build_quiz_session — could be anything)
        session = fake_context.user_data["quiz_session"]
        # Trim to 1 question for predictable test
        session.questions = session.questions[:1]
        q = session.questions[0]
        # Force quiz_type translate so we can answer with text
        if q.quiz_type != "translate":
            from bot.quiz import _generate_translate

            session.questions[0] = _generate_translate(q.word)
        q = session.questions[0]

        # Send answer
        upd_text = fake_update(text=q.correct_answer)
        await quiz_text_answer(upd_text, fake_context)

        # Send rating
        upd_rate = fake_update(callback_data="rate:4")
        result = await quiz_rating(upd_rate, fake_context)
        assert result == ConversationHandler.END

        # Verify SM-2 was persisted
        state = await get_sm2_state(db, 12345, word_id, q.quiz_type)
        assert state is not None
        assert state["correct_count"] == 1

    async def test_quiz_cancel(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, quiz_cancel

        fake_context.user_data["quiz_session"] = "dummy"
        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        assert "quiz_session" not in fake_context.user_data

    async def test_quiz_start_clears_stale_state(self, fake_update, fake_context, db):
        """Re-entering /quiz should clear any stale session state from a previous run."""
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
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
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = ["5"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 5

    async def test_quiz_size_and_tag(self, fake_update, fake_context, db):
        """`/quiz 3 animals` filters by tag and uses requested size."""
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast", tags="animals")
        await add_word(db, 12345, "adj", "langsam", "slow", tags="other")
        fake_context.args = ["3", "animals"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 3
        # Only words tagged "animals" should appear
        assert all(q.word["german"] == "schnell" for q in session.questions)

    async def test_quiz_args_order_independent(self, fake_update, fake_context, db):
        """`/quiz animals 3` parses the same as `/quiz 3 animals`."""
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast", tags="animals")
        fake_context.args = ["animals", "3"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 3

    async def test_quiz_size_capped(self, fake_update, fake_context, db):
        """Requested size above QUIZ_MAX_SIZE is capped, with a notice in the start message."""
        from bot.config import QUIZ_MAX_SIZE
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = [str(QUIZ_MAX_SIZE + 100)]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == QUIZ_MAX_SIZE
        # Start message should mention the cap
        first_call_text = upd.message.reply_text.call_args_list[0].args[0]
        assert "Capped" in first_call_text

    async def test_quiz_zero_size_rejected(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import ConversationHandler, quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = ["0"]
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "positive" in text.lower()

    async def test_quiz_repeat_notice_when_vocab_smaller(self, fake_update, fake_context, db):
        """Start message tells the user words will repeat when vocab < size."""
        from bot.database import add_word
        from bot.handlers import quiz_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        fake_context.args = ["10"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        first_call_text = upd.message.reply_text.call_args_list[0].args[0]
        assert "repeat" in first_call_text.lower()

    async def test_text_answer_when_session_finished(self, fake_update, fake_context, db):
        from bot.handlers import ConversationHandler, quiz_text_answer
        from bot.quiz import QuizSession

        session = QuizSession(user_id=12345, questions=[])
        fake_context.user_data["quiz_session"] = session
        upd = fake_update(text="something")
        result = await quiz_text_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No active quiz" in text

    async def test_misspell_callback_repeats_word(self, fake_update, fake_context, db):
        """Tapping Misspell records None in results and adds the word again."""
        from bot.database import add_word
        from bot.handlers import (
            QUIZ_ANSWERING,
            quiz_rating,
            quiz_start,
            quiz_text_answer,
        )
        from bot.quiz import _generate_translate

        await add_word(db, 12345, "adj", "schnell", "fast")
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
        from bot.handlers import QUIZ_RATING, quiz_button_answer
        from bot.quiz import QuizQuestion, QuizSession

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
        q = QuizQuestion(
            word=word,
            quiz_type="multiple_choice",
            prompt="What does 'die Katze' mean?",
            options=["cat", "dog", "mouse", "bird"],
            correct_answer="cat",
        )
        session = QuizSession(user_id=12345, questions=[q])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="mc:cat")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is True
        # Edit text should mention "Correct"
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Correct" in text

    async def test_button_answer_multiple_choice_wrong(self, fake_update, fake_context, db):
        from bot.handlers import QUIZ_RATING, quiz_button_answer
        from bot.quiz import QuizQuestion, QuizSession

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
        q = QuizQuestion(
            word=word,
            quiz_type="multiple_choice",
            prompt="What does 'die Katze' mean?",
            options=["cat", "dog", "mouse", "bird"],
            correct_answer="cat",
        )
        session = QuizSession(user_id=12345, questions=[q])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="mc:dog")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is False
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "Wrong" in text

    async def test_button_answer_article(self, fake_update, fake_context, db):
        from bot.handlers import QUIZ_RATING, quiz_button_answer
        from bot.quiz import QuizQuestion, QuizSession

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
        q = QuizQuestion(
            word=word,
            quiz_type="article",
            prompt="What is the article for 'Katze'?",
            options=["der", "die", "das"],
            correct_answer="die",
        )
        session = QuizSession(user_id=12345, questions=[q])
        fake_context.user_data["quiz_session"] = session

        upd = fake_update(callback_data="art:die")
        result = await quiz_button_answer(upd, fake_context)
        assert result == QUIZ_RATING
        assert fake_context.user_data["last_answer_correct"] is True

    async def test_button_answer_no_session(self, fake_update, fake_context, db):
        from bot.handlers import ConversationHandler, quiz_button_answer

        upd = fake_update(callback_data="mc:something")
        result = await quiz_button_answer(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "No active quiz" in text


class TestSaveWordsValueError:
    async def test_value_error_caught_and_reported(self, fake_update, fake_context, db):
        """If add_word raises ValueError, _save_words should report it without crashing."""
        from bot.handlers import _save_words

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


class TestFinishQuizPartialFailure:
    async def test_one_word_fails_others_succeed(self, fake_update, fake_context, db, monkeypatch):
        """If one upsert raises, the summary still includes a note about failures."""
        import bot.handlers as h
        from bot.database import add_word

        wid1 = await add_word(db, 12345, "adj", "schnell", "fast")
        await add_word(db, 12345, "adj", "langsam", "slow")
        upd = fake_update()
        await h.quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        # Force 2 translate questions
        from bot.quiz import _generate_translate

        session.questions = [_generate_translate(q.word) for q in session.questions[:2]]
        if len(session.questions) < 2:
            return  # skip if only 1 word selected for the session

        # Mark both questions answered
        session.results = [(4, True), (4, True)]
        session.current_index = 2

        # Patch upsert_sm2_state in bot.quiz (where apply_results uses it)
        import bot.quiz as q

        original = q.upsert_sm2_state

        async def failing_upsert(conn, user_id, word_id, *args, **kwargs):
            if word_id == wid1:
                raise RuntimeError("simulated failure")
            return await original(conn, user_id, word_id, *args, **kwargs)

        monkeypatch.setattr(q, "upsert_sm2_state", failing_upsert)

        # Build a fake query with .message.reply_text
        fake_query = fake_update(callback_data="rate:4")
        result = await h._finish_quiz(fake_query.callback_query, fake_context)
        assert result == h.ConversationHandler.END
        # Last reply should be the summary including the failure note
        summary = fake_query.callback_query.message.reply_text.call_args.args[0]
        assert "could not be saved" in summary


class TestSafeLog:
    def test_strips_control_chars(self):
        from bot.handlers import _safe_log

        assert _safe_log("hello\nworld") == "hello?world"
        assert _safe_log("\x1b[31mred\x1b[0m") == "?[31mred?[0m"

    def test_truncates_long(self):
        from bot.handlers import _safe_log

        result = _safe_log("a" * 500)
        assert result.endswith("...")
        assert len(result) <= 220  # within reason

    def test_none(self):
        from bot.handlers import _safe_log

        assert _safe_log(None) == ""
        assert _safe_log("") == ""


class TestFormatAnswerResponse:
    def test_correct_format(self):
        from bot.handlers import _format_answer_response
        from bot.quiz import QuizQuestion

        q = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        text = _format_answer_response(q, correct=True)
        assert "Correct" in text
        assert "die Katze" in text

    def test_wrong_format(self):
        from bot.handlers import _format_answer_response
        from bot.quiz import QuizQuestion

        q = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        text = _format_answer_response(q, correct=False)
        assert "Wrong" in text

    def test_html_escape(self):
        from bot.handlers import _format_answer_response
        from bot.quiz import QuizQuestion

        # Use a value that doesn't collide with the wrapper <b> tag
        q = QuizQuestion(
            word={"german": "<script>", "translation": "x", "part_of_speech": "adj"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="<script>alert(1)</script>",
        )
        text = _format_answer_response(q, correct=True)
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


class TestBuildQuestionMarkup:
    def test_multiple_choice_layout(self):
        from bot.handlers import _build_question_markup
        from bot.quiz import QuizQuestion

        q = QuizQuestion(
            word={"german": "x", "translation": "y", "part_of_speech": "n"},
            quiz_type="multiple_choice",
            prompt="p",
            options=["a", "b", "c", "d"],
            correct_answer="a",
        )
        markup = _build_question_markup(q)
        # multiple_choice puts each option on its own row
        assert len(markup.inline_keyboard) == 4

    def test_article_layout(self):
        from bot.handlers import _build_question_markup
        from bot.quiz import QuizQuestion

        q = QuizQuestion(
            word={"german": "Katze", "translation": "cat", "part_of_speech": "n"},
            quiz_type="article",
            prompt="p",
            options=["der", "die", "das"],
            correct_answer="die",
        )
        markup = _build_question_markup(q)
        # article puts all 3 in one row
        assert len(markup.inline_keyboard) == 1
        assert len(markup.inline_keyboard[0]) == 3

    def test_translate_no_markup(self):
        from bot.handlers import _build_question_markup
        from bot.quiz import QuizQuestion

        q = QuizQuestion(
            word={"german": "x", "translation": "y", "part_of_speech": "adj"},
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="x",
        )
        assert _build_question_markup(q) is None


class TestAddEmptyInput:
    async def test_empty_text_no_words(self, fake_update, fake_context, db):
        from bot.handlers import ADD_WORDS, add_words_received

        fake_context.user_data["add_tag"] = ""
        upd = fake_update(text="\n\n   \n")
        result = await add_words_received(upd, fake_context)
        assert result == ADD_WORDS
        text = upd.message.reply_text.call_args.args[0]
        assert "No valid words" in text


class TestAddStartClearsStale:
    async def test_clears_stale_state(self, fake_update, fake_context):
        from bot.handlers import add_start

        fake_context.user_data["parsed_words"] = [{"old": True}]
        fake_context.user_data["add_tag"] = "old_tag"
        upd = fake_update()
        await add_start(upd, fake_context)
        # parsed_words must be cleared; add_tag is overwritten with the new value
        assert "parsed_words" not in fake_context.user_data
        assert fake_context.user_data["add_tag"] == ""
