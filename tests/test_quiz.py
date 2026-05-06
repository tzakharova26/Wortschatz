import json
import random
from datetime import datetime, timedelta

from bot.config import (
    QUALITY_BLACKOUT,
    QUALITY_EASY,
    QUALITY_GOOD,
    QUALITY_WRONG,
    QUIZ_START_MESSAGE,
    QUIZ_TYPE_WEIGHTS,
)
from bot.quiz import (
    QuizQuestion,
    QuizSession,
    _word_score,
    build_quiz_session,
    check_answer,
    format_summary,
    generate_question,
    select_quiz_type,
)


def _make_word(
    word_id=1,
    pos="n",
    german="Katze",
    translation="cat",
    article="die",
    plural="Katzen",
    irregular_forms=None,
    tags="",
    earliest_review=None,
):
    return {
        "id": word_id,
        "user_id": 12345,
        "part_of_speech": pos,
        "german": german,
        "article": article,
        "plural": plural,
        "partizip_ii": None,
        "irregular_forms": json.dumps(irregular_forms) if irregular_forms else None,
        "translation": translation,
        "tags": tags,
        "earliest_review": earliest_review,
    }


def _make_verb(word_id=2, irregular=True):
    forms = {"ich": "fahre", "du": "f\u00e4hrst", "er": "f\u00e4hrt"} if irregular else None
    return _make_word(
        word_id=word_id,
        pos="v",
        german="fahren",
        translation="to drive",
        article=None,
        plural=None,
        irregular_forms=forms,
    )


def _make_adj(word_id=3):
    return _make_word(
        word_id=word_id,
        pos="adj",
        german="schnell",
        translation="fast",
        article=None,
        plural=None,
    )


def _make_adv(word_id=4):
    return _make_word(
        word_id=word_id,
        pos="adv",
        german="manchmal",
        translation="sometimes",
        article=None,
        plural=None,
    )


# --- Config constants ---


class TestConfigConstants:
    def test_quality_values(self):
        assert QUALITY_BLACKOUT == 0
        assert QUALITY_WRONG == 1
        assert QUALITY_GOOD == 4
        assert QUALITY_EASY == 5

    def test_quiz_start_message_exists(self):
        assert "Blackout" in QUIZ_START_MESSAGE
        assert "Wrong" in QUIZ_START_MESSAGE
        assert "Good" in QUIZ_START_MESSAGE
        assert "Easy" in QUIZ_START_MESSAGE
        assert "Misspell" in QUIZ_START_MESSAGE

    def test_quiz_type_weights(self):
        assert QUIZ_TYPE_WEIGHTS["translate"] == 1.0
        assert QUIZ_TYPE_WEIGHTS["verb_forms"] == 0.9
        assert QUIZ_TYPE_WEIGHTS["multiple_choice"] == 0.6
        assert QUIZ_TYPE_WEIGHTS["article"] == 0.5


# --- Word score ---


class TestWordScore:
    def test_never_reviewed_high_score(self):
        word = _make_word(earliest_review=None)
        now = datetime(2026, 5, 6)
        score = _word_score(word, now, temperature=0.3)
        assert score > 1000  # (365+1)^(1/0.3) is very large

    def test_recently_reviewed_low_score(self):
        now = datetime(2026, 5, 6)
        word = _make_word(earliest_review=now.isoformat())
        score = _word_score(word, now, temperature=0.3)
        assert score == 1.0  # (0+1)^(1/0.3) = 1

    def test_overdue_word_higher_score(self):
        now = datetime(2026, 5, 6)
        recent = _make_word(word_id=1, earliest_review=(now - timedelta(days=1)).isoformat())
        old = _make_word(word_id=2, earliest_review=(now - timedelta(days=30)).isoformat())
        assert _word_score(old, now, 0.3) > _word_score(recent, now, 0.3)

    def test_epoch_treated_as_never_reviewed(self):
        word = _make_word(earliest_review="1970-01-01")
        now = datetime(2026, 5, 6)
        score = _word_score(word, now, temperature=0.3)
        assert score > 1000

    def test_invalid_review_date(self):
        word = _make_word()
        word["earliest_review"] = "not-a-date"
        now = datetime(2026, 5, 6)
        score = _word_score(word, now, temperature=0.3)
        assert score > 1000  # falls back to 365 days


# --- Quiz type selection ---


class TestSelectQuizType:
    def test_noun_types(self):
        word = _make_word()
        types_seen = set()
        for _ in range(100):
            types_seen.add(select_quiz_type(word))
        assert types_seen <= {"translate", "multiple_choice", "article"}

    def test_regular_verb_no_verb_forms(self):
        word = _make_verb(irregular=False)
        for _ in range(50):
            qt = select_quiz_type(word)
            assert qt in ("translate", "multiple_choice")

    def test_irregular_verb_can_get_verb_forms(self):
        word = _make_verb(irregular=True)
        types_seen = set()
        for _ in range(100):
            types_seen.add(select_quiz_type(word))
        assert "verb_forms" in types_seen

    def test_adjective_types(self):
        word = _make_adj()
        for _ in range(50):
            qt = select_quiz_type(word)
            assert qt in ("translate", "multiple_choice")

    def test_adverb_types(self):
        word = _make_adv()
        for _ in range(50):
            qt = select_quiz_type(word)
            assert qt in ("translate", "multiple_choice")

    def test_temperature_affects_selection(self):
        """With the same word, temperature param should not crash."""
        word = _make_word()
        now = datetime(2026, 5, 6)
        select_quiz_type(word, temperature=0.1, now=now)
        select_quiz_type(word, temperature=1.0, now=now)

    def test_zero_temperature_does_not_crash(self):
        word = _make_word()
        now = datetime(2026, 5, 6)
        select_quiz_type(word, temperature=0, now=now)  # should not ZeroDivisionError


# --- Question generation ---


class TestGenerateQuestion:
    def test_translate_noun_includes_article(self):
        word = _make_word()
        q = generate_question(word, "translate", [word])
        assert q.correct_answer == "die Katze"
        assert q.quiz_type == "translate"
        assert word["translation"] in q.prompt

    def test_translate_noun_without_article(self):
        word = _make_word(article=None)
        q = generate_question(word, "translate", [word])
        assert q.correct_answer == "Katze"

    def test_translate_verb(self):
        word = _make_verb()
        q = generate_question(word, "translate", [word])
        assert q.correct_answer == "fahren"

    def test_multiple_choice_has_options(self):
        words = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_word(word_id=2, german="Hund", translation="dog"),
            _make_word(word_id=3, german="Maus", translation="mouse"),
            _make_word(word_id=4, german="Vogel", translation="bird"),
        ]
        q = generate_question(words[0], "multiple_choice", words)
        assert q.options is not None
        assert "cat" in q.options
        assert len(q.options) == 4

    def test_multiple_choice_few_words(self):
        words = [_make_word(word_id=1)]
        q = generate_question(words[0], "multiple_choice", words)
        assert q.options is not None
        assert "cat" in q.options
        assert len(q.options) == 1  # only correct answer

    def test_multiple_choice_two_words(self):
        words = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_word(word_id=2, german="Hund", translation="dog"),
        ]
        q = generate_question(words[0], "multiple_choice", words)
        assert len(q.options) == 2

    def test_multiple_choice_three_words(self):
        words = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_word(word_id=2, german="Hund", translation="dog"),
            _make_word(word_id=3, german="Maus", translation="mouse"),
        ]
        q = generate_question(words[0], "multiple_choice", words)
        assert len(q.options) == 3

    def test_multiple_choice_cross_pos_fallback(self):
        words = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_adj(word_id=2),
        ]
        q = generate_question(words[0], "multiple_choice", words)
        assert len(q.options) == 2

    def test_multiple_choice_dedup_translations(self):
        words = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_word(word_id=2, german="Kater", translation="cat"),
            _make_word(word_id=3, german="Hund", translation="dog"),
        ]
        q = generate_question(words[0], "multiple_choice", words)
        # "cat" appears twice but dedup keeps only one wrong "dog"
        assert q.options.count("cat") == 1

    def test_article_quiz(self):
        word = _make_word(article="die")
        q = generate_question(word, "article", [word])
        assert q.options == ["der", "die", "das"]
        assert q.correct_answer == "die"

    def test_article_quiz_no_article_falls_back(self):
        word = _make_word(article=None)
        q = generate_question(word, "article", [word])
        assert q.quiz_type == "translate"  # fallback

    def test_verb_forms_quiz(self):
        word = _make_verb(irregular=True)
        random.seed(42)
        q = generate_question(word, "verb_forms", [word])
        assert q.verb_form_key in ("ich", "du", "er")
        assert q.correct_answer in ("fahre", "f\u00e4hrst", "f\u00e4hrt")

    def test_verb_forms_no_forms_falls_back(self):
        word = _make_verb(irregular=False)
        q = generate_question(word, "verb_forms", [word])
        assert q.quiz_type == "translate"

    def test_verb_forms_empty_value_falls_back(self):
        word = _make_word(
            pos="v", german="testen", translation="to test", article=None, plural=None
        )
        word["irregular_forms"] = json.dumps({"ich": ""})
        q = generate_question(word, "verb_forms", [word])
        assert q.quiz_type == "translate"  # empty form value

    def test_unknown_quiz_type_falls_back(self):
        word = _make_word()
        q = generate_question(word, "unknown_type", [word])
        assert q.quiz_type == "translate"


# --- Check answer ---


class TestCheckAnswer:
    def test_translate_correct(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="Translate: cat",
            options=None,
            correct_answer="die Katze",
        )
        assert check_answer(q, "die Katze")
        assert check_answer(q, "Die katze")

    def test_translate_umlaut_simplified(self):
        q = QuizQuestion(
            word=_make_verb(),
            quiz_type="translate",
            prompt="Translate: to drive",
            options=None,
            correct_answer="fahren",
        )
        assert check_answer(q, "fahren")

    def test_translate_wrong(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="Translate: cat",
            options=None,
            correct_answer="die Katze",
        )
        assert not check_answer(q, "der Hund")

    def test_multiple_choice_correct(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="multiple_choice",
            prompt="What does 'die Katze' mean?",
            options=["cat", "dog", "mouse"],
            correct_answer="cat",
        )
        assert check_answer(q, "cat")
        assert check_answer(q, "Cat")

    def test_article_correct(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="article",
            prompt="Article for Katze?",
            options=["der", "die", "das"],
            correct_answer="die",
        )
        assert check_answer(q, "die")
        assert not check_answer(q, "der")

    def test_verb_forms_umlaut_tolerance(self):
        q = QuizQuestion(
            word=_make_verb(),
            quiz_type="verb_forms",
            prompt="du form of fahren?",
            options=None,
            correct_answer="f\u00e4hrst",
            verb_form_key="du",
        )
        assert check_answer(q, "faehrst")
        assert check_answer(q, "f\u00e4hrst")

    def test_empty_answer(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        assert not check_answer(q, "")
        assert not check_answer(q, "   ")

    def test_none_correct_answer(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="article",
            prompt="p",
            options=["der", "die", "das"],
            correct_answer=None,
        )
        assert not check_answer(q, "die")


# --- Quiz session ---


class TestQuizSession:
    def test_session_flow(self):
        q1 = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        q2 = QuizQuestion(
            word=_make_adj(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="schnell",
        )
        session = QuizSession(user_id=12345, questions=[q1, q2])

        assert not session.is_finished
        assert session.current_question == q1

        session.record_result(quality=4, correct=True)
        assert session.current_question == q2

        session.record_result(quality=1, correct=False)
        assert session.is_finished
        assert session.score == (1, 2)
        assert session.current_question is None

    def test_record_result_on_finished_is_noop(self):
        session = QuizSession(user_id=12345, questions=[])
        assert session.is_finished
        session.record_result(quality=4, correct=True)
        assert len(session.results) == 0  # no-op

    def test_empty_session_score(self):
        session = QuizSession(user_id=12345, questions=[])
        assert session.score == (0, 0)

    def test_invalid_quality_clamped(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=10, correct=True)
        assert session.results[0] == (5, True)  # clamped to 5

    def test_misspell_adds_question(self):
        word = _make_word()
        q1 = QuizQuestion(
            word=word,
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q1])
        all_words = [word]
        session.add_misspell_question(word, all_words)
        assert len(session.questions) == 2

    def test_misspell_on_finished_reopens(self):
        word = _make_word()
        q1 = QuizQuestion(
            word=word,
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q1])
        session.record_result(quality=4, correct=True)
        assert session.is_finished
        session.add_misspell_question(word, [word])
        assert not session.is_finished

    def test_record_misspell_inserts_none(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_misspell()
        assert session.results == [None]
        assert session.is_finished
        assert session.score == (0, 0)  # misspell excluded

    def test_misspell_mid_session_preserves_later_results(self):
        """Regression: misspell should not break SM-2 update for subsequent questions."""
        word = _make_word()
        q1 = QuizQuestion(
            word=_make_word(word_id=1),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        q2 = QuizQuestion(
            word=_make_word(word_id=2),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="der Hund",
        )
        q3 = QuizQuestion(
            word=_make_word(word_id=3),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="das Auto",
        )
        session = QuizSession(user_id=12345, questions=[q1, q2, q3])

        session.record_result(quality=4, correct=True)  # q1 done
        session.add_misspell_question(word, [word])  # adds q4 at end
        session.record_misspell()  # q2 marked misspell
        session.record_result(quality=4, correct=True)  # q3 done

        assert session.results == [(4, True), None, (4, True)]
        assert session.score == (2, 2)
        # q2's slot is None — not lost from results

    def test_record_misspell_on_finished_is_noop(self):
        session = QuizSession(user_id=12345, questions=[])
        session.record_misspell()
        assert session.results == []


# --- Build session ---


class TestBuildQuizSession:
    def test_builds_correct_count(self):
        words = [
            _make_word(word_id=i, german=f"word{i}", translation=f"trans{i}") for i in range(3)
        ]
        session = build_quiz_session(user_id=12345, due_words=words, all_words=words)
        assert len(session.questions) == 3
        assert session.user_id == 12345

    def test_empty_words(self):
        session = build_quiz_session(user_id=12345, due_words=[], all_words=[])
        assert len(session.questions) == 0
        assert session.is_finished

    def test_mixed_word_types(self):
        words = [_make_word(word_id=1), _make_verb(word_id=2), _make_adj(word_id=3)]
        session = build_quiz_session(user_id=12345, due_words=words, all_words=words)
        assert len(session.questions) == 3

    def test_all_words_larger_than_due(self):
        due = [_make_word(word_id=1, german="Katze", translation="cat")]
        all_w = [
            _make_word(word_id=1, german="Katze", translation="cat"),
            _make_word(word_id=2, german="Hund", translation="dog"),
            _make_word(word_id=3, german="Maus", translation="mouse"),
            _make_word(word_id=4, german="Vogel", translation="bird"),
        ]
        session = build_quiz_session(user_id=12345, due_words=due, all_words=all_w)
        assert len(session.questions) == 1

    def test_passes_now_to_select(self):
        now = datetime(2026, 5, 6)
        words = [_make_word()]
        session = build_quiz_session(user_id=12345, due_words=words, all_words=words, now=now)
        assert len(session.questions) == 1


# --- Format summary ---


class TestFormatSummary:
    def test_summary_format(self):
        q1 = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        q2 = QuizQuestion(
            word=_make_adj(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="schnell",
        )
        session = QuizSession(user_id=12345, questions=[q1, q2])
        session.record_result(quality=4, correct=True)
        session.record_result(quality=1, correct=False)
        summary = format_summary(session)
        assert "1/2 correct" in summary
        assert "+ die Katze" in summary
        assert "- schnell" in summary

    def test_verb_forms_in_summary(self):
        word = _make_verb()
        q = QuizQuestion(
            word=word,
            quiz_type="verb_forms",
            prompt="du form?",
            options=None,
            correct_answer="f\u00e4hrst",
            verb_form_key="du",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=4, correct=True)
        summary = format_summary(session)
        assert "(du)" in summary
        assert "f\u00e4hrst" in summary

    def test_empty_session_summary(self):
        session = QuizSession(user_id=12345, questions=[])
        summary = format_summary(session)
        assert "0/0 correct" in summary

    def test_all_correct_summary(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=5, correct=True)
        summary = format_summary(session)
        assert "1/1 correct" in summary
        assert "+" in summary

    def test_all_wrong_summary(self):
        q = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=0, correct=False)
        summary = format_summary(session)
        assert "0/1 correct" in summary
        assert "-" in summary

    def test_partial_session_summary(self):
        """Summary for a session that wasn't fully completed."""
        q1 = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        q2 = QuizQuestion(
            word=_make_adj(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="schnell",
        )
        session = QuizSession(user_id=12345, questions=[q1, q2])
        session.record_result(quality=4, correct=True)
        # q2 not answered
        summary = format_summary(session)
        assert "1/1 correct" in summary
        assert "schnell" not in summary  # unanswered question not shown

    def test_noun_without_article_in_summary(self):
        word = _make_word(article=None)
        q = QuizQuestion(
            word=word,
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="Katze",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=4, correct=True)
        summary = format_summary(session)
        assert "+ Katze" in summary

    def test_summary_skips_misspell(self):
        q1 = QuizQuestion(
            word=_make_word(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="die Katze",
        )
        q2 = QuizQuestion(
            word=_make_adj(),
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="schnell",
        )
        session = QuizSession(user_id=12345, questions=[q1, q2])
        session.record_result(quality=4, correct=True)
        session.record_misspell()
        summary = format_summary(session)
        assert "1/1 correct" in summary
        assert "die Katze" in summary
        assert "schnell" not in summary  # misspell line is skipped

    def test_summary_html_escapes_user_content(self):
        word = _make_word(german="<script>", translation="<b>cat</b>", article=None)
        q = QuizQuestion(
            word=word,
            quiz_type="translate",
            prompt="p",
            options=None,
            correct_answer="<script>",
        )
        session = QuizSession(user_id=12345, questions=[q])
        session.record_result(quality=4, correct=True)
        summary = format_summary(session)
        assert "<script>" not in summary
        assert "<b>cat</b>" not in summary
        assert "&lt;script&gt;" in summary
        assert "&lt;b&gt;cat&lt;/b&gt;" in summary
