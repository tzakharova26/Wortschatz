from bot.umlaut import answers_match, convert_umlauts, normalize_for_comparison


class TestConvertUmlauts:
    def test_basic_conversions(self):
        assert convert_umlauts("faehrt") == "f\u00e4hrt"
        assert convert_umlauts("schoen") == "sch\u00f6n"
        assert convert_umlauts("ueber") == "\u00fcber"
        assert convert_umlauts("Strasse") == "Stra\u00dfe"

    def test_uppercase(self):
        assert convert_umlauts("Aerger") == "\u00c4rger"
        assert convert_umlauts("Oesterreich") == "\u00d6sterreich"
        assert convert_umlauts("Uebung") == "\u00dcbung"

    def test_no_change(self):
        assert convert_umlauts("Hund") == "Hund"
        assert convert_umlauts("") == ""

    def test_already_unicode(self):
        assert convert_umlauts("f\u00e4hrt") == "f\u00e4hrt"

    def test_multiple_umlauts(self):
        assert convert_umlauts("Maedchen") == "M\u00e4dchen"


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

    def test_umlaut_ascii(self):
        assert answers_match("faehrt", "f\u00e4hrt")

    def test_umlaut_unicode(self):
        assert answers_match("f\u00e4hrt", "f\u00e4hrt")

    def test_eszett(self):
        assert answers_match("Strasse", "Stra\u00dfe")

    def test_mismatch(self):
        assert not answers_match("Katze", "Hund")
