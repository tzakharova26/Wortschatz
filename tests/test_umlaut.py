from bot.umlaut import answers_match, normalize_for_comparison


class TestNormalizeForComparison:
    def test_lowercases(self):
        assert normalize_for_comparison("Hund") == "hund"

    def test_replaces_umlauts(self):
        assert normalize_for_comparison("f\u00e4hrt") == "faehrt"
        assert normalize_for_comparison("sch\u00f6n") == "schoen"
        assert normalize_for_comparison("\u00fcber") == "ueber"
        assert normalize_for_comparison("Stra\u00dfe") == "strasse"

    def test_strips_whitespace(self):
        assert normalize_for_comparison("  Hund  ") == "hund"


class TestAnswersMatch:
    def test_exact_match(self):
        assert answers_match("Hund", "Hund")

    def test_case_insensitive(self):
        assert answers_match("hund", "Hund")

    def test_mismatch(self):
        assert not answers_match("Katze", "Hund")

    # User simplifies special chars (allowed)
    def test_user_types_ae_for_umlaut(self):
        assert answers_match("faehrt", "f\u00e4hrt")

    def test_user_types_oe_for_umlaut(self):
        assert answers_match("schoen", "sch\u00f6n")

    def test_user_types_ue_for_umlaut(self):
        assert answers_match("ueber", "\u00fcber")

    def test_user_types_ss_for_eszett(self):
        assert answers_match("Strasse", "Stra\u00dfe")

    def test_user_types_exact_umlaut(self):
        assert answers_match("f\u00e4hrt", "f\u00e4hrt")

    def test_user_types_exact_eszett(self):
        assert answers_match("\u00df", "\u00df")

    # User adds false special chars (NOT allowed)
    def test_user_adds_umlaut_where_none(self):
        # stored "a", user typed "ä" -> wrong
        assert not answers_match("k\u00e4tze", "katze")

    def test_user_adds_eszett_where_ss(self):
        # stored "ss", user typed "ß" -> wrong
        assert not answers_match("Stra\u00dfe", "Strasse")

    def test_user_adds_oe_where_plain_o(self):
        assert not answers_match("sch\u00f6n", "schon")

    def test_user_adds_ue_where_plain_u(self):
        assert not answers_match("\u00fcber", "uber")

    # User drops umlaut (wrong — expanded forms won't match)
    def test_user_drops_umlaut(self):
        # stored "ä", user typed "a" -> "a" != "ae" -> wrong
        assert not answers_match("fahrt", "f\u00e4hrt")

    def test_user_drops_eszett(self):
        # stored "ß", user typed just "s" -> "s" != "ss" -> wrong
        assert not answers_match("Strase", "Stra\u00dfe")

    # Mixed cases
    def test_multiple_umlauts_simplified(self):
        assert answers_match("Maedchen", "M\u00e4dchen")

    def test_whitespace_tolerance(self):
        assert answers_match("  f\u00e4hrt  ", "f\u00e4hrt")

    def test_article_with_noun(self):
        assert answers_match("die Katze", "die Katze")
        assert not answers_match("der Katze", "die Katze")

    def test_empty_strings(self):
        assert answers_match("", "")
        assert not answers_match("", "Hund")
        assert not answers_match("Hund", "")
