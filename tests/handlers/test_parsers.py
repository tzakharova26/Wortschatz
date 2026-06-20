"""Tests for bot/handlers/parsers.py — the pure /add line parsers."""

from bot.handlers import _parse_word_line


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

    def test_noun_without_plural_marker(self):
        word, err = _parse_word_line("n das Geld - money")
        assert err is None
        assert word["part_of_speech"] == "n"
        assert word["article"] == "das"
        assert word["german"] == "Geld"
        assert word["plural"] is None
        assert word["translation"] == "money"

    def test_noun_pipe_without_plural_marker(self):
        word, err = _parse_word_line("n | die | Bildung | — | education")
        assert err is None
        assert word["plural"] is None
        assert word["translation"] == "education"

    def test_regular_verb(self):
        word, err = _parse_word_line("v machen to do")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "machen"
        assert word["translation"] == "to do"
        assert word["irregular_forms"] is None

    def test_irregular_verb(self):
        # Input is preserved exactly — no auto-umlaut conversion at /add time.
        word, err = _parse_word_line("vi fahren ist gefahren fahre faehrst faehrt to drive")
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "fahren"
        assert word["irregular_forms"] == {
            "partizip_ii": "ist gefahren",
            "ich": "fahre",
            "du": "faehrst",
            "er": "faehrt",
        }
        assert word["translation"] == "to drive"

    def test_irregular_verb_preserves_unicode_umlauts(self):
        word, err = _parse_word_line("vi fahren ist gefahren fahre fährst fährt to drive")
        assert err is None
        assert word["irregular_forms"]["du"] == "fährst"

    def test_regular_verb_with_long_translation_not_misparsed(self):
        word, err = _parse_word_line("v gehen to walk on foot")
        assert err is None
        assert word["irregular_forms"] is None
        assert word["translation"] == "to walk on foot"

    def test_irregular_verb_single_partizip(self):
        word, err = _parse_word_line("vi sehen gesehen sehe siehst sieht to see")
        assert err is None
        assert word["irregular_forms"] == {
            "partizip_ii": "gesehen",
            "ich": "sehe",
            "du": "siehst",
            "er": "sieht",
        }
        assert word["translation"] == "to see"

    def test_irregular_verb_multi_word_translation(self):
        # Input preserved exactly — no auto-conversion.
        word, err = _parse_word_line("vi laufen ist gelaufen laufe laeufst laeuft to run very fast")
        assert err is None
        assert word["irregular_forms"] == {
            "partizip_ii": "ist gelaufen",
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
        assert word["translation"] == "hat gemacht to do something"
        assert word["irregular_forms"] is None

    def test_verb_pipe_with_short_irregular_forms(self):
        word, err = _parse_word_line("v | bringen | p=hat gebracht | pr=brachte | to bring")
        assert err is None
        assert word["irregular_forms"] == {
            "partizip_ii": "hat gebracht",
            "preteritum": "brachte",
        }
        assert word["translation"] == "to bring"

    def test_verb_pipe_with_person_specific_preteritum(self):
        word, err = _parse_word_line(
            "v | sein | p=ist gewesen | pr_ich=war | pr-du=warst | pr_er=war | to be"
        )
        assert err is None
        assert word["irregular_forms"] == {
            "partizip_ii": "ist gewesen",
            "preteritum_ich": "war",
            "preteritum_du": "warst",
            "preteritum_er": "war",
        }
        assert word["translation"] == "to be"

    def test_irregular_verb_pipe(self):
        word, err = _parse_word_line(
            "vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive a car"
        )
        assert err is None
        assert word["part_of_speech"] == "v"
        assert word["german"] == "fahren"
        # Input preserved verbatim — no auto-conversion.
        assert word["irregular_forms"] == {
            "partizip_ii": "ist gefahren",
            "ich": "fahre",
            "du": "faehrst",
            "er": "faehrt",
        }
        assert word["translation"] == "to drive a car"

    def test_regular_verb_pipe_too_few(self):
        word, err = _parse_word_line("v | machen")
        assert word is None
        assert err is not None and "v |" in err

    def test_irregular_verb_pipe_too_few(self):
        word, err = _parse_word_line("vi | fahren | ist gefahren | fahre | faehrst")
        assert word is None
        assert err is not None and "irregular forms" in err

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
        assert err is None
        assert word["translation"] == "hat"

    def test_verb_ist_too_few(self):
        word, err = _parse_word_line("v fahren")
        assert word is None
        assert "Too few" in err

    def test_unknown_pos(self):
        word, err = _parse_word_line("xyz something translation")
        assert word is None
        assert "Unknown" in err

    def test_umlaut_input_preserved_ascii(self):
        """Users may write ae/oe/ue/ss for ä/ö/ü/ß. Whatever they wrote is what
        gets stored — no auto-conversion (auto-conversion frequently misspelled words)."""
        word, err = _parse_word_line("adj schoen beautiful")
        assert err is None
        assert word["german"] == "schoen"

    def test_umlaut_input_preserved_unicode(self):
        """Users can also type real umlauts directly — those are preserved too."""
        word, err = _parse_word_line("adj schön beautiful")
        assert err is None
        assert word["german"] == "schön"

    def test_eszett_input_preserved(self):
        """ß stays ß; ss stays ss — whichever the user wrote."""
        unicode_word, err = _parse_word_line("n die Straße Straßen street")
        assert err is None
        assert unicode_word["german"] == "Straße"
        assert unicode_word["plural"] == "Straßen"

        ascii_word, err = _parse_word_line("n die Strasse Strassen street")
        assert err is None
        assert ascii_word["german"] == "Strasse"
        assert ascii_word["plural"] == "Strassen"

    def test_noun_with_umlaut_preserved(self):
        word, err = _parse_word_line("n das Mädchen Mädchen girl")
        assert err is None
        assert word["german"] == "Mädchen"
        assert word["plural"] == "Mädchen"

    def test_verb_partizip_with_umlaut_preserved(self):
        word, err = _parse_word_line("v | fahren | p=gefahren | to drive")
        assert err is None
        assert word["irregular_forms"]["partizip_ii"] == "gefahren"
        # And the unicode variant on partizip
        word2, err2 = _parse_word_line("v | hören | p=gehört | to hear")
        assert err2 is None
        assert word2["german"] == "hören"
        assert word2["irregular_forms"]["partizip_ii"] == "gehört"

    def test_verb_single_partizip(self):
        """Verb with single-word partizip (no ist/hat prefix)."""
        word, err = _parse_word_line("v | spielen | p=gespielt | to play")
        assert err is None
        assert word["irregular_forms"]["partizip_ii"] == "gespielt"
        assert word["translation"] == "to play"

    def test_adj_multi_word_translation(self):
        word, err = _parse_word_line("adj gut very good")
        assert err is None
        assert word["translation"] == "very good"

    def test_phrase_space_separated(self):
        word, err = _parse_word_line("phrase morgens in the morning")
        assert err is None
        assert word["part_of_speech"] == "phrase"
        assert word["german"] == "morgens"
        assert word["translation"] == "in the morning"

    def test_phrase_pipe_separated(self):
        word, err = _parse_word_line("phrase | auf jeden Fall | in any case")
        assert err is None
        assert word["part_of_speech"] == "phrase"
        assert word["german"] == "auf jeden Fall"
        assert word["translation"] == "in any case"

    def test_phrase_short_marker(self):
        word, err = _parse_word_line("phr | sich Mühe geben | to make an effort")
        assert err is None
        assert word["part_of_speech"] == "phrase"
        assert word["german"] == "sich Mühe geben"
        assert word["translation"] == "to make an effort"


class TestParseWordLineHtmlEscaping:
    def test_error_message_escapes_user_input(self):
        word, err = _parse_word_line("xyz <script>alert(1)</script>")
        assert word is None
        assert "<script>" not in err
        assert "&lt;" in err
