import json
import random
from datetime import datetime

from bot.database import (
    add_quiz_history,
    add_word,
    get_needs_learning_words,
    get_sm2_state,
    upsert_sm2_state,
)
from bot.learn import (
    ADJECTIVE_EXAMPLE,
    ARTICLE,
    MAX_STEP_ATTEMPTS,
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

    async def test_learning_status_filters_new_and_blackout(self, db):
        new_id = await add_word(db, USER_ID, "adj", "neu", "new")
        blackout_id = await add_word(db, USER_ID, "adj", "alt", "old")
        await add_quiz_history(db, USER_ID, blackout_id, "translate", correct=False)
        await upsert_sm2_state(
            db,
            USER_ID,
            blackout_id,
            "translate",
            easiness_factor=1.7,
            interval=1,
            repetitions=0,
            correct_count=0,
            next_review=datetime.now(),
            last_quality=0,
        )

        new_words = await get_needs_learning_words(db, USER_ID, learning_status="new")
        blackout_words = await get_needs_learning_words(db, USER_ID, learning_status="blackout")

        assert [w["id"] for w in new_words] == [new_id]
        assert [w["id"] for w in blackout_words] == [blackout_id]

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
    def test_adjective_includes_example_form_step(self):
        words = [_word(1, pos="adj")]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert types == [SHOW, MC, TYPED, ADJECTIVE_EXAMPLE]
        assert s.required_per_word[1] == {SHOW, MC, TYPED, ADJECTIVE_EXAMPLE}
        assert "___" in s.steps[-1].prompt

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
        assert plural_step.correct_answer == "die Katzen"
        assert "die Katze" in plural_step.prompt

    def test_noun_without_plural_skips_plural_step(self):
        words = [_word(1, pos="n", german="Milch", article="die", plural="", translation="milk")]
        s = build_session(USER_ID, words, words)
        types = [step.step_type for step in s.steps]
        assert PLURAL not in types
        assert types == [SHOW, MC, TYPED, ARTICLE]

    def test_irregular_verb_two_form_steps(self):
        forms = json.dumps(
            {
                "partizip_ii": "ist gefahren",
                "preteritum": "fuhr",
                "ich": "fahre",
                "du": "fährst",
                "er": "fährt",
            }
        )
        words = [
            _word(
                1,
                pos="v",
                german="fahren",
                irregular_forms=forms,
                translation="to drive",
            )
        ]
        s = build_session(USER_ID, words, words)
        verb_steps = [step for step in s.steps if step.step_type == VERB_FORM]
        assert len(verb_steps) == 5
        # Each verb_form step has a distinct key recorded as required
        keys = {f"{VERB_FORM}:{step.verb_form_key}" for step in verb_steps}
        assert keys == {
            f"{VERB_FORM}:partizip_ii",
            f"{VERB_FORM}:preteritum",
            f"{VERB_FORM}:ich",
            f"{VERB_FORM}:du",
            f"{VERB_FORM}:er",
        }
        assert keys.issubset(s.required_per_word[1])

    def test_regular_verb_has_partizip_and_one_present_form_step(self):
        random.seed(1)
        words = [_word(1, pos="v", german="machen", translation="to do")]
        s = build_session(USER_ID, words, words)
        verb_steps = [step for step in s.steps if step.step_type == VERB_FORM]
        assert len(verb_steps) == 2
        assert verb_steps[0].verb_form_key == "partizip_ii"
        assert verb_steps[0].correct_answer == "hat gemacht"
        assert verb_steps[1].verb_form_key in {"ich", "du", "er", "wir", "ihr", "sie"}

    def test_multi_word_steps_interleaved(self):
        """With ≥2 words, no two consecutive steps should be from the same word."""
        words = [
            _word(1, pos="adj", german="schnell", translation="fast"),
            _word(2, pos="adj", german="langsam", translation="slow"),
            _word(3, pos="adj", german="müde", translation="tired"),
        ]
        session = build_session(USER_ID, words, words)
        # Each adj contributes 4 steps × 3 words = 12 total
        assert len(session.steps) == 12
        # No same word twice in a row
        ids = [step.word["id"] for step in session.steps]
        for prev, curr in zip(ids, ids[1:], strict=False):
            assert prev != curr, f"consecutive steps on same word: {ids}"
        # Per-word pedagogical order preserved (SHOW → MC → TYPED → ADJECTIVE_EXAMPLE)
        for word_id in (1, 2, 3):
            order = [step.step_type for step in session.steps if step.word["id"] == word_id]
            assert order == [SHOW, MC, TYPED, ADJECTIVE_EXAMPLE]


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
        assert s.steps[-1].attempt == 2
        assert s.steps[-1].step_type == MC
        # A correct retry graduates the word
        s.record_step(correct=True)
        assert s.is_finished
        assert s.graduated_words() == [w]

    def test_second_retry_can_graduate_word(self):
        w = _word(1)
        steps = [_show(w), _typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {SHOW, TYPED}})
        s.record_step(correct=True)  # show
        s.record_step(correct=False)  # typed wrong, retry 1 queued
        s.record_step(correct=False)  # retry 1 wrong, retry 2 queued
        assert s.steps[-1].attempt == MAX_STEP_ATTEMPTS
        s.record_step(correct=True)  # retry 2 correct
        assert s.is_finished
        assert s.graduated_words() == [w]

    def test_failure_after_second_retry_means_no_graduation(self):
        w = _word(1)
        steps = [_show(w), _typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {SHOW, TYPED}})
        s.record_step(correct=True)  # show
        s.record_step(correct=False)  # typed wrong, retry queued
        s.record_step(correct=False)  # retry 1 also wrong, retry 2 queued
        s.record_step(correct=False)  # retry 2 also wrong
        assert s.is_finished
        assert s.graduated_words() == []  # word stays in needs-learning

    def test_retry_only_queued_twice(self):
        """A step that fails three times doesn't generate a fourth attempt."""
        w = _word(1)
        steps = [_typed(w)]
        s = LearnSession(user_id=USER_ID, steps=steps, required_per_word={1: {TYPED}})
        s.record_step(correct=False)  # 1st attempt: wrong, retry queued
        s.record_step(correct=False)  # 2nd attempt: wrong, final retry queued
        s.record_step(correct=False)  # 3rd attempt: wrong, NO new retry
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

    def test_plural_accepts_umlaut_digraph(self):
        """User typing 'haefen' for stored plural 'Häfen' must count as right."""
        w = _word(1, pos="n", german="Hafen", article="der", plural="Häfen", translation="harbor")
        step = LearnStep(
            word=w,
            step_type=PLURAL,
            prompt="plural?",
            options=None,
            correct_answer="die Häfen",
        )
        assert check_answer(step, "haefen") is True
        assert check_answer(step, "die haefen") is True
        assert check_answer(step, "Häfen") is True
        assert check_answer(step, "die Häfen") is True
        assert check_answer(step, "Hafen") is False  # missing umlaut, no digraph

    def test_plural_accepts_ss_for_eszett(self):
        """User typing 'Strassen' (ss) for stored 'Straßen' (ß) must count as right."""
        w = _word(
            1, pos="n", german="Straße", article="die", plural="Straßen", translation="street"
        )
        step = LearnStep(
            word=w,
            step_type=PLURAL,
            prompt="plural?",
            options=None,
            correct_answer="die Straßen",
        )
        assert check_answer(step, "Strassen") is True
        assert check_answer(step, "die Strassen") is True
        assert check_answer(step, "Straßen") is True

    def test_plural_strips_die_on_either_side(self):
        """``die <plural>`` and bare ``<plural>`` are interchangeable."""
        w = _word(1, pos="n", german="Katze", article="die", plural="Katzen", translation="cat")
        step = LearnStep(
            word=w,
            step_type=PLURAL,
            prompt="plural?",
            options=None,
            correct_answer="die Katzen",
        )
        assert check_answer(step, "Katzen") is True
        assert check_answer(step, "die Katzen") is True
        assert check_answer(step, "der Katzen") is False  # wrong article still rejected


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
        state = await get_sm2_state(db, USER_ID, wid, "translate")
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

    async def test_savepoint_failure_isolates_one_pair(self, db, monkeypatch):
        """If sm2 upsert fails for one (word, quiz_type) pair, the SAVEPOINT
        rollback must keep the other pairs and the rest of the batch intact."""
        import bot.learn as learn_module

        wid_ok = await add_word(db, USER_ID, "adj", "schnell", "fast")
        wid_bad = await add_word(db, USER_ID, "adj", "langsam", "slow")
        word_ok = _word(wid_ok, pos="adj", german="schnell", translation="fast")
        word_bad = _word(wid_bad, pos="adj", german="langsam", translation="slow")
        s = LearnSession(
            user_id=USER_ID,
            steps=[_show(word_ok), _show(word_bad)],
            required_per_word={wid_ok: {SHOW, MC, TYPED}, wid_bad: {SHOW, MC, TYPED}},
            word_step_passed={
                wid_ok: {SHOW, MC, TYPED},
                wid_bad: {SHOW, MC, TYPED},
            },
        )

        original_upsert = learn_module.upsert_sm2_state

        async def selective_failure(conn, user_id, word_id, *args, **kwargs):
            # Fail only for wid_bad+translate; everything else works.
            if word_id == wid_bad and args and args[0] == "translate":
                raise RuntimeError("savepoint should isolate this")
            if word_id == wid_bad and "quiz_type" in kwargs and kwargs["quiz_type"] == "translate":
                raise RuntimeError("savepoint should isolate this")
            return await original_upsert(conn, user_id, word_id, *args, **kwargs)

        monkeypatch.setattr(learn_module, "upsert_sm2_state", selective_failure)
        graduated = await apply_graduations(db, s)
        # Both words still report as graduated (count is by required_per_word, not
        # per-pair). The point is the batch survives — we then prove the OK pair
        # actually committed.
        assert graduated == 2
        ok_state = await get_sm2_state(db, USER_ID, wid_ok, "translate")
        assert ok_state is not None  # OK pair persisted

    def test_show_prompt_includes_tags(self):
        """SHOW step prompt surfaces the word's tags when present (line 158)."""
        from bot.learn import _show_prompt

        word = _word(1, pos="adj", german="schnell", translation="fast", tags="A1,speed")
        prompt = _show_prompt(word)
        assert "A1,speed" in prompt

    def test_show_prompt_formats_verb_forms_as_table(self):
        from bot.learn import _show_prompt

        word = _word(
            1,
            pos="v",
            german="sein",
            translation="to be",
            irregular_forms=json.dumps(
                {
                    "partizip_ii": "ist gewesen",
                    "preteritum_ich": "war",
                    "preteritum_du": "warst",
                }
            ),
        )
        prompt = _show_prompt(word)
        assert "<pre>" in prompt
        assert "Partizip II" in prompt
        assert "Präteritum du" in prompt


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
