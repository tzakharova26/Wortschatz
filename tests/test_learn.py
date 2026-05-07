import json
from datetime import datetime

from bot.database import (
    add_quiz_history,
    add_word,
    get_needs_learning_words,
    get_sm2_state,
    upsert_sm2_state,
)
from bot.learn import (
    ARTICLE,
    LEARN_VERB_FORMS_COUNT,
    MC,
    PLURAL,
    SHOW,
    TYPED,
    VERB_FORM,
    LearnSession,
    LearnStep,
    apply_graduations,
    build_session,
    check_answer,
    format_summary,
)

USER_ID = 12345


def _word(
    word_id: int,
    pos: str = "adj",
    german: str = "schnell",
    translation: str = "fast",
    article: str | None = None,
    plural: str | None = None,
    partizip_ii: str | None = None,
    irregular_forms: str | None = None,
    tags: str = "",
) -> dict:
    return {
        "id": word_id,
        "user_id": USER_ID,
        "part_of_speech": pos,
        "german": german,
        "article": article,
        "plural": plural,
        "partizip_ii": partizip_ii,
        "irregular_forms": irregular_forms,
        "translation": translation,
        "tags": tags,
    }


# --- DB-level: needs-learning eligibility ---


class TestNeedsLearningWords:
    async def test_brand_new_word_qualifies(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast")
        words = await get_needs_learning_words(db, USER_ID)
        assert [w["id"] for w in words] == [wid]

    async def test_seen_word_excluded(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, wid, "translate", correct=True)
        await upsert_sm2_state(
            db,
            USER_ID,
            wid,
            "translate",
            easiness_factor=2.5,
            interval=1,
            repetitions=1,
            correct_count=1,
            next_review=datetime.now(),
            last_quality=4,
        )
        words = await get_needs_learning_words(db, USER_ID)
        assert words == []

    async def test_blackout_demotes_word(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_quiz_history(db, USER_ID, wid, "translate", correct=False)
        await upsert_sm2_state(
            db,
            USER_ID,
            wid,
            "translate",
            easiness_factor=1.7,
            interval=1,
            repetitions=0,
            correct_count=0,
            next_review=datetime.now(),
            last_quality=0,
        )
        words = await get_needs_learning_words(db, USER_ID)
        assert [w["id"] for w in words] == [wid]

    async def test_filter_by_tag(self, db):
        w1 = await add_word(db, USER_ID, "adj", "schnell", "fast", tags="A1")
        await add_word(db, USER_ID, "adj", "langsam", "slow", tags="A2")
        words = await get_needs_learning_words(db, USER_ID, tag="A1")
        assert [w["id"] for w in words] == [w1]

    async def test_filter_by_word_ids(self, db):
        w1 = await add_word(db, USER_ID, "adj", "schnell", "fast")
        w2 = await add_word(db, USER_ID, "adj", "langsam", "slow")
        await add_word(db, USER_ID, "adj", "müde", "tired")
        words = await get_needs_learning_words(db, USER_ID, word_ids=[w1, w2])
        assert sorted(w["id"] for w in words) == sorted([w1, w2])

    async def test_limit(self, db):
        for i in range(5):
            await add_word(db, USER_ID, "adj", f"word{i}", f"trans{i}")
        words = await get_needs_learning_words(db, USER_ID, limit=2)
        assert len(words) == 2


# --- Session step generation ---


class TestBuildSession:
    def test_adjective_three_steps(self):
        words = [_word(1, pos="adj")]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert types == [SHOW, MC, TYPED]
        assert s.required_per_word[1] == {SHOW, MC, TYPED}

    def test_noun_includes_article_and_plural_steps(self):
        words = [
            _word(
                1,
                pos="n",
                german="Katze",
                article="die",
                plural="Katzen",
                translation="cat",
            )
        ]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert types == [SHOW, MC, TYPED, ARTICLE, PLURAL]
        # plural step should ask for the plural with article context
        plural_step = s.steps[-1]
        assert plural_step.correct_answer == "Katzen"
        assert "die Katze" in plural_step.prompt

    def test_noun_without_plural_skips_plural_step(self):
        words = [_word(1, pos="n", german="Milch", article="die", plural="", translation="milk")]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert PLURAL not in types
        assert types == [SHOW, MC, TYPED, ARTICLE]

    def test_irregular_verb_two_form_steps(self):
        forms = json.dumps({"ich": "fahre", "du": "fährst", "er": "fährt"})
        words = [
            _word(
                1,
                pos="v",
                german="fahren",
                partizip_ii="ist gefahren",
                irregular_forms=forms,
                translation="to drive",
            )
        ]
        s = build_session(USER_ID, words, words)
        verb_steps = [step for step in s.steps if step.step_type == VERB_FORM]
        assert len(verb_steps) == LEARN_VERB_FORMS_COUNT
        # Each verb_form step has a distinct key recorded as required
        keys = {f"{VERB_FORM}:{step.verb_form_key}" for step in verb_steps}
        assert keys.issubset(s.required_per_word[1])

    def test_regular_verb_no_form_steps(self):
        words = [_word(1, pos="v", german="machen", partizip_ii="hat gemacht", translation="to do")]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert types == [SHOW, MC, TYPED]


# --- Step recording, retry queue, graduation ---


def _show(word):
    return LearnStep(word=word, step_type=SHOW, prompt="card", options=None, correct_answer=None)


def _typed(word, answer="schnell"):
    return LearnStep(word=word, step_type=TYPED, prompt="type", options=None, correct_answer=answer)


def _mc(word, answer="fast"):
    return LearnStep(
        word=word, step_type=MC, prompt="mc", options=["fast", "slow"], correct_answer=answer
    )


class TestRecordStep:
    def test_correct_step_marked_passed(self):
        w = _word(1)
        steps = [_show(w), _mc(w), _typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {SHOW, MC, TYPED}})
        s.record_step(correct=True)
        s.record_step(correct=True)
        s.record_step(correct=True)
        assert s.is_finished
        assert s.word_step_passed[1] == {SHOW, MC, TYPED}
        assert s.graduated_words() == [w]

    def test_wrong_step_appended_to_retry(self):
        w = _word(1)
        steps = [_show(w), _mc(w), _typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {SHOW, MC, TYPED}})
        s.record_step(correct=True)  # show
        s.record_step(correct=False)  # mc -> retry queued
        s.record_step(correct=True)  # typed
        # Now main run is done; retry queue should be appended
        assert s.retries_appended is True
        assert len(s.steps) == 4  # original 3 + 1 retry
        assert s.steps[-1].is_retry is True
        assert s.steps[-1].step_type == MC
        # A correct retry graduates the word
        s.record_step(correct=True)
        assert s.is_finished
        assert s.graduated_words() == [w]

    def test_retry_failure_means_no_graduation(self):
        w = _word(1)
        steps = [_show(w), _typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {SHOW, TYPED}})
        s.record_step(correct=True)  # show
        s.record_step(correct=False)  # typed wrong, retry queued
        s.record_step(correct=False)  # retry also wrong
        assert s.is_finished
        assert s.graduated_words() == []  # word stays in needs-learning

    def test_retry_only_queued_once(self):
        """A retry that fails doesn't generate another retry."""
        w = _word(1)
        steps = [_typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {TYPED}})
        s.record_step(correct=False)  # 1st attempt: wrong, retry queued
        s.record_step(correct=False)  # retry attempt: wrong, NO new retry
        assert s.is_finished
        assert s.retries_appended


# --- check_answer ---


class TestCheckAnswer:
    def test_show_always_passes(self):
        w = _word(1)
        assert check_answer(_show(w), "anything") is True

    def test_mc_case_insensitive(self):
        w = _word(1)
        step = _mc(w, answer="Cat")
        assert check_answer(step, "cat") is True
        assert check_answer(step, "dog") is False

    def test_typed_uses_umlaut_tolerance(self):
        w = _word(1)
        step = _typed(w, answer="Mädchen")
        assert check_answer(step, "Maedchen") is True
        assert check_answer(step, "Madchen") is False  # missing umlaut → wrong

    def test_empty_answer_wrong(self):
        w = _word(1)
        assert check_answer(_typed(w), "   ") is False
        assert check_answer(_mc(w), "") is False


# --- apply_graduations ---


class TestApplyGraduations:
    async def test_seeds_sm2_for_all_quiz_types(self, db):
        wid = await add_word(db, USER_ID, "n", "Katze", "cat", article="die", plural="Katzen")
        word = _word(
            wid, pos="n", german="Katze", article="die", plural="Katzen", translation="cat"
        )
        s = LearnSession(
            user_id=USER_ID,
            steps=[_show(word), _mc(word), _typed(word, answer="die Katze")],
            required_per_word={wid: {SHOW, MC, TYPED, ARTICLE, PLURAL}},
            word_step_passed={wid: {SHOW, MC, TYPED, ARTICLE, PLURAL}},
        )
        graduated = await apply_graduations(db, s)
        assert graduated == 1
        # Nouns get translate, MC, article, plural SM-2 entries
        for qt in ("translate", "multiple_choice", "article", "plural"):
            state = await get_sm2_state(db, USER_ID, wid, qt)
            assert state is not None
            assert state["last_quality"] == 4

    async def test_does_not_graduate_failed_word(self, db):
        wid = await add_word(db, USER_ID, "adj", "schnell", "fast")
        word = _word(wid)
        s = LearnSession(
            user_id=USER_ID,
            steps=[_show(word), _typed(word)],
            required_per_word={wid: {SHOW, TYPED}},
            word_step_passed={wid: {SHOW}},  # typed never passed
        )
        graduated = await apply_graduations(db, s)
        assert graduated == 0
        assert await get_sm2_state(db, USER_ID, wid, "translate") is None


# --- format_summary ---


class TestFormatSummary:
    def test_lists_graduated_and_remaining(self):
        w_pass = _word(1, german="schnell", translation="fast")
        w_fail = _word(2, german="langsam", translation="slow")
        s = LearnSession(
            user_id=USER_ID,
            steps=[_show(w_pass), _typed(w_pass), _show(w_fail), _typed(w_fail)],
            required_per_word={1: {SHOW, TYPED}, 2: {SHOW, TYPED}},
            word_step_passed={1: {SHOW, TYPED}, 2: {SHOW}},
        )
        text = format_summary(s)
        assert "Graduated 1/2" in text
        assert "schnell" in text
        assert "langsam" in text
