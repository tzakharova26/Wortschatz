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
        # Input is preserved exactly \u2014 no auto-umlaut conversion at /add time.
        word, err = _parse_word_line("vi fahren ist gefahren fahre faehrst faehrt to drive")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "fahren"
        assert word["partizip_ii"] == "ist gefahren"
        assert word["irregular_forms"] == {"ich": "fahre", "du": "faehrst", "er": "faehrt"}
        assert word["translation"] == "to drive"

    def test_irregular_verb_preserves_unicode_umlauts(self):
        word, err = _parse_word_line("vi fahren ist gefahren fahre f\u00e4hrst f\u00e4hrt to drive")
        assert err is None
        assert word["irregular_forms"] == {"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"}

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
        # Input preserved exactly \u2014 no auto-conversion.
        word, err = _parse_word_line("vi laufen ist gelaufen laufe laeufst laeuft to run very fast")
        assert err is None
        assert word["irregular_forms"] == {
            "ich": "laufe",
            "du": "laeufst",
            "er": "laeuft",
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
        # Input preserved verbatim — no auto-conversion.
        assert word["irregular_forms"] == {
            "ich": "fahre",
            "du": "faehrst",
            "er": "faehrt",
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

    def test_umlaut_input_preserved_ascii(self):
        """Users may write ae/oe/ue/ss for \u00e4/\u00f6/\u00fc/\u00df. Whatever they wrote is what
        gets stored \u2014 no auto-conversion (auto-conversion frequently misspelled words)."""
        word, err = _parse_word_line("adj schoen beautiful")
        assert err is None
        assert word["german"] == "schoen"

    def test_umlaut_input_preserved_unicode(self):
        """Users can also type real umlauts directly \u2014 those are preserved too."""
        word, err = _parse_word_line("adj sch\u00f6n beautiful")
        assert err is None
        assert word["german"] == "sch\u00f6n"

    def test_eszett_input_preserved(self):
        """\u00df stays \u00df; ss stays ss \u2014 whichever the user wrote."""
        unicode_word, err = _parse_word_line("n die Stra\u00dfe Stra\u00dfen street")
        assert err is None
        assert unicode_word["german"] == "Stra\u00dfe"
        assert unicode_word["plural"] == "Stra\u00dfen"

        ascii_word, err = _parse_word_line("n die Strasse Strassen street")
        assert err is None
        assert ascii_word["german"] == "Strasse"
        assert ascii_word["plural"] == "Strassen"

    def test_noun_with_umlaut_preserved(self):
        word, err = _parse_word_line("n das M\u00e4dchen M\u00e4dchen girl")
        assert err is None
        assert word["german"] == "M\u00e4dchen"
        assert word["plural"] == "M\u00e4dchen"

    def test_verb_partizip_with_umlaut_preserved(self):
        word, err = _parse_word_line("v fahren gefahren to drive")
        assert err is None
        assert word["partizip_ii"] == "gefahren"
        # And the unicode variant on partizip
        word2, err2 = _parse_word_line("v h\u00f6ren geh\u00f6rt to hear")
        assert err2 is None
        assert word2["german"] == "h\u00f6ren"
        assert word2["partizip_ii"] == "geh\u00f6rt"

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

    def test_show_ids_false_drops_id_prefix(self):
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
        text = _format_word_tables(words, show_ids=False)
        assert "[1]" not in text
        assert "[2]" not in text
        # Word data still present
        assert "Katze" in text
        assert "schnell" in text


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
        # Preview now uses inline buttons (Confirm + Cancel) instead of /confirm and /cancel
        assert "Confirm" in ADD_FORMAT_MESSAGE
        assert "Cancel" in ADD_FORMAT_MESSAGE

    def test_start_message_has_all_commands(self):
        from bot.handlers import START_MESSAGE

        for cmd in ("/add", "/list", "/tags", "/delete", "/quiz", "/stats", "/help"):
            assert cmd in START_MESSAGE
        # Should also explain rating buttons (via QUIZ_START_MESSAGE)
        assert "Misspell" in START_MESSAGE

    def test_commands_help_escapes_angle_brackets(self):
        """`<id|all>` etc. must be escaped — Telegram parses parse_mode=HTML strictly
        and rejects unknown tags, which once broke /start and the /help Commands button."""
        from bot.handlers import COMMANDS_HELP, START_MESSAGE

        # The placeholder for /remindoff must be the escaped form.
        assert "&lt;id|all&gt;" in COMMANDS_HELP
        assert "<id|all>" not in COMMANDS_HELP
        assert "<id|all>" not in START_MESSAGE


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

    async def test_delete_requires_exact_match(self, fake_update, fake_context, db):
        """/delete uses the literal text the user typed — no umlaut conversion.
        Matches storage policy: words are stored verbatim, so deletion must
        match verbatim too."""
        from bot.database import add_word, get_words
        from bot.handlers import delete_command

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
        assert "Learn & quiz" in button_texts


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

    async def test_practice_topic(self, fake_update, fake_context):
        from bot.handlers import help_callback

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
        """Error handler must log with full traceback. Specifically: a record
        from ``bot.handlers.simple`` must carry ``exc_info`` whose first element
        is the actual ValueError. Loose 'or' on getMessage was almost-unfailable."""
        import logging

        from bot.handlers import error_handler

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
        """All-valid input goes to preview (ADD_CONFIRM) with Confirm/Cancel buttons,
        no DB writes yet."""
        from bot.database import get_words
        from bot.handlers import ADD_CONFIRM, CB_ADD, add_words_received

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
        from bot.database import get_words
        from bot.handlers import ConversationHandler, add_callback

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
        from bot.handlers import ConversationHandler, add_callback

        upd = fake_update(callback_data="add:confirm")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
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
        from bot.handlers import ConversationHandler, add_callback

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
        from bot.database import add_word, get_words
        from bot.handlers import add_callback

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
        from bot.database import add_word, get_words
        from bot.handlers import add_callback

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
        from bot.handlers import ConversationHandler, add_callback

        fake_context.user_data["parsed_words"] = [{"x": 1}]
        fake_context.user_data["add_tag"] = "tag"
        upd = fake_update(callback_data="add:cancel")
        result = await add_callback(upd, fake_context)
        assert result == ConversationHandler.END
        assert "parsed_words" not in fake_context.user_data
        assert "add_tag" not in fake_context.user_data
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "cancelled" in text.lower()


# --- /quiz conversation flow ---


class TestQuizConversation:
    async def test_quiz_start_no_words(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, quiz_start

        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "No words to quiz" in text
        # Empty vocabulary → suggest /add (not /learn).
        assert "/add" in text
        assert "/learn" not in text

    async def test_quiz_start_with_words(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import QUIZ_ANSWERING, quiz_start
        from tests.helpers import graduate_word

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)  # /quiz only sees graduated words
        upd = fake_update()
        result = await quiz_start(upd, fake_context)
        assert result == QUIZ_ANSWERING
        assert "quiz_session" in fake_context.user_data

    async def test_quiz_skips_brand_new_words(self, fake_update, fake_context, db):
        """A word with no quiz_history is in /learn pool, not /quiz."""
        from bot.database import add_word
        from bot.handlers import ConversationHandler, quiz_start

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
        from tests.helpers import graduate_word

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
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

        # Verify SM-2 was persisted (graduate_word seeded correct_count=1, then
        # one more correct answer makes it 2). The intent is just that the rating
        # round-tripped to the DB.
        state = await get_sm2_state(db, 12345, word_id, q.quiz_type)
        assert state is not None
        assert state["correct_count"] >= 2

    async def test_quiz_cancel_no_session(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, quiz_cancel

        upd = fake_update()
        result = await quiz_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert text == "Quiz cancelled."

    async def test_quiz_cancel_clears_unanswered_session(self, fake_update, fake_context, db):
        """Cancelling with zero rated answers shouldn't write SM-2 state."""
        from bot.database import add_word, get_sm2_state
        from bot.handlers import ConversationHandler, quiz_cancel
        from bot.quiz import QuizSession

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
        from bot.database import add_word, get_sm2_state
        from bot.handlers import ConversationHandler, quiz_cancel
        from bot.quiz import QuizSession, _generate_translate

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
        from bot.database import add_word
        from bot.handlers import quiz_start
        from tests.helpers import graduate_word

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
        from bot.database import add_word
        from bot.handlers import quiz_start
        from tests.helpers import graduate_word

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
        fake_context.args = ["5"]
        upd = fake_update()
        await quiz_start(upd, fake_context)
        session = fake_context.user_data["quiz_session"]
        assert len(session.questions) == 5

    async def test_quiz_size_and_tag(self, fake_update, fake_context, db):
        """`/quiz 3 animals` filters by tag and uses requested size."""
        from bot.database import add_word
        from bot.handlers import quiz_start
        from tests.helpers import graduate_word

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
        from bot.database import add_word
        from bot.handlers import quiz_start
        from tests.helpers import graduate_word

        word_id = await add_word(db, 12345, "adj", "schnell", "fast", tags="animals")
        await graduate_word(db, word_id)
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
        from tests.helpers import graduate_word

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
        from tests.helpers import graduate_word

        word_id = await add_word(db, 12345, "adj", "schnell", "fast")
        await graduate_word(db, word_id)
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
        from tests.helpers import graduate_word

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
        """If one upsert raises, the summary still includes a note about failures.

        Build the session by hand so the test deterministically exercises the
        2-word failure branch — relying on quiz_start could give us a 1-word
        session (cycling) and silently skip the assertion.
        """
        import bot.handlers as h
        import bot.quiz as q
        from bot.database import add_quiz_history, add_word
        from bot.handlers.quiz import _finish_quiz
        from bot.quiz import QuizSession, _generate_translate
        from tests.helpers import graduate_word

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


class TestApplyResultsAtomicity:
    """Per-row (sm2_state + quiz_history) pair must be atomic. If sm2 upsert
    fails, no quiz_history row should be written for that question — and
    other questions in the session should still persist normally."""

    async def test_failed_question_writes_neither_sm2_nor_history(self, db, monkeypatch):
        from bot.database import add_quiz_history, add_word, get_sm2_state
        from bot.quiz import QuizQuestion, QuizSession, apply_results
        from tests.helpers import graduate_word

        wid_ok = await add_word(db, 12345, "adj", "schnell", "fast")
        wid_bad = await add_word(db, 12345, "adj", "langsam", "slow")
        await graduate_word(db, wid_ok)
        await graduate_word(db, wid_bad)

        # Snapshot pre-state
        history_before = await db.execute(
            "SELECT COUNT(*) FROM quiz_history WHERE user_id = ? AND word_id = ?",
            (12345, wid_bad),
        )
        before_count = (await history_before.fetchone())[0]

        questions = [
            QuizQuestion(
                word={
                    "id": wid_ok,
                    "user_id": 12345,
                    "part_of_speech": "adj",
                    "german": "schnell",
                    "translation": "fast",
                    "article": None,
                    "plural": None,
                    "partizip_ii": None,
                    "irregular_forms": None,
                },
                quiz_type="translate",
                prompt="x",
                options=None,
                correct_answer="schnell",
            ),
            QuizQuestion(
                word={
                    "id": wid_bad,
                    "user_id": 12345,
                    "part_of_speech": "adj",
                    "german": "langsam",
                    "translation": "slow",
                    "article": None,
                    "plural": None,
                    "partizip_ii": None,
                    "irregular_forms": None,
                },
                quiz_type="translate",
                prompt="x",
                options=None,
                correct_answer="langsam",
            ),
        ]
        session = QuizSession(
            user_id=12345, questions=questions, current_index=2, results=[(4, True), (4, True)]
        )

        # Patch upsert to fail only for the bad word — quiz_history should NOT
        # be written for that word either (savepoint rollback proves atomicity).
        import bot.quiz as q

        original_upsert = q.upsert_sm2_state

        async def failing_upsert(conn, user_id, word_id, *args, **kwargs):
            if word_id == wid_bad:
                raise RuntimeError("boom")
            return await original_upsert(conn, user_id, word_id, *args, **kwargs)

        monkeypatch.setattr(q, "upsert_sm2_state", failing_upsert)
        failures = await apply_results(db, session)
        assert failures == 1

        # Bad word: sm2_state NOT updated (graduate_word's last_quality=4 still there)
        bad_state = await get_sm2_state(db, 12345, wid_bad, "translate")
        assert bad_state is not None
        # Bad word: NO new quiz_history row appended
        history_after = await db.execute(
            "SELECT COUNT(*) FROM quiz_history WHERE user_id = ? AND word_id = ?",
            (12345, wid_bad),
        )
        after_count = (await history_after.fetchone())[0]
        assert after_count == before_count, "quiz_history should not advance for failed word"

        # Good word: history DID advance
        good_history = await db.execute(
            "SELECT COUNT(*) FROM quiz_history WHERE user_id = ? AND word_id = ?",
            (12345, wid_ok),
        )
        good_count = (await good_history.fetchone())[0]
        assert good_count >= 2  # graduate_word seeded 1, apply_results added 1 more

        # Silence unused fixture warning
        _ = add_quiz_history  # noqa


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


class TestLearnConversation:
    async def test_learn_start_with_no_eligible_words(self, fake_update, fake_context, db):
        from bot.handlers import ConversationHandler, learn_start

        upd = fake_update()
        result = await learn_start(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "Nothing to learn" in text

    async def test_learn_start_builds_session_for_new_word(self, fake_update, fake_context, db):
        from bot.database import add_word
        from bot.handlers import LEARN_ANSWERING, learn_start

        await add_word(db, 12345, "adj", "schnell", "fast")
        upd = fake_update()
        result = await learn_start(upd, fake_context)
        assert result == LEARN_ANSWERING
        session = fake_context.user_data["learn_session"]
        # adj → 3 steps: show, mc, typed
        assert len(session.steps) == 3

    async def test_learn_size_below_minimum_is_bumped(self, fake_update, fake_context, db):
        """`/learn 2` should be bumped to LEARN_MIN_SIZE before the session is built."""
        from bot.config import LEARN_MIN_SIZE
        from bot.database import add_word
        from bot.handlers import learn_start

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
        from bot.database import add_word, get_due_words
        from bot.handlers import learn_button_answer, learn_start, learn_text_answer

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
        from bot.database import add_word, get_due_words, get_needs_learning_words
        from bot.handlers import learn_button_answer, learn_start, learn_text_answer

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
        from bot.database import add_word
        from bot.handlers import LEARN_ANSWERING, learn_batch_callback

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
        from bot.handlers import ConversationHandler, learn_batch_callback

        upd = fake_update(callback_data="lbatch:go")
        result = await learn_batch_callback(upd, fake_context)
        assert result == ConversationHandler.END
        text = upd.callback_query.message.reply_text.call_args.args[0]
        assert "no longer available" in text.lower()

    async def test_learn_cancel(self, fake_update, fake_context):
        from bot.handlers import ConversationHandler, learn_cancel
        from bot.learn import LearnSession

        fake_context.user_data["learn_session"] = LearnSession(
            user_id=12345, steps=[], required_per_word={}
        )
        upd = fake_update()
        result = await learn_cancel(upd, fake_context)
        assert result == ConversationHandler.END
        assert "learn_session" not in fake_context.user_data

    async def test_save_words_attaches_start_learning_button(self, fake_update, fake_context, db):
        """After /add confirms with new words, the success reply has a Start learning button."""
        from bot.handlers import CB_LEARN_BATCH, _save_words

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
        from bot.database import add_word
        from bot.handlers import _save_words

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
