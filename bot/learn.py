"""Learning flow for new (or recently Blackout-flagged) words.

Distinct from /quiz: each word gets a rapid-fire massed drill — show the card,
then recognize via multiple choice, then produce via typed answer, then any
POS-specific extras (article for nouns, two verb forms for irregular verbs).

Wrong steps are retried up to two times at the end of the session.
A word graduates only if every required step passes within those attempts.
Graduating writes synthetic Good ratings into SM-2 and quiz_history so the
word becomes eligible for /quiz from then on.
"""

from __future__ import annotations

import html
import random
from dataclasses import dataclass, field

from bot.database import (
    WORD_REVIEW_STATE,
    add_quiz_history,
    get_quiz_types_for_word,
    get_sm2_state,
    parse_irregular_forms,
    upsert_sm2_state,
)
from bot.logging_config import get_logger, log_user_action, log_user_error
from bot.questions import (
    german_with_article,
    is_correct,
    multiple_choice_options,
)
from bot.sm2 import QUALITY_CORRECT, calculate_sm2, sm2_from_db

logger = get_logger(__name__)

# Step types
SHOW = "show"
MC = "multiple_choice"
TYPED = "typed"
ARTICLE = "article"
PLURAL = "plural"
PARTIZIP = "partizip"
VERB_FORM = "verb_form"

# Drill this many distinct verb forms (out of ich/du/er) for irregular verbs.
LEARN_VERB_FORMS_COUNT = 2
MAX_STEP_ATTEMPTS = 3


@dataclass
class LearnStep:
    word: dict
    step_type: str
    prompt: str
    options: list[str] | None  # set for MC and ARTICLE
    correct_answer: str | None  # None for SHOW
    verb_form_key: str | None = None
    attempt: int = 1


@dataclass
class LearnSession:
    user_id: int
    steps: list[LearnStep]
    required_per_word: dict[int, set[str]]
    current_index: int = 0
    word_step_passed: dict[int, set[str]] = field(default_factory=dict)
    retry_queue: list[LearnStep] = field(default_factory=list)
    retries_appended: bool = False

    @property
    def is_finished(self) -> bool:
        return self.current_index >= len(self.steps)

    @property
    def current_step(self) -> LearnStep | None:
        if self.is_finished:
            return None
        return self.steps[self.current_index]

    def step_key(self, step: LearnStep) -> str:
        if step.step_type == VERB_FORM:
            return f"{VERB_FORM}:{step.verb_form_key}"
        return step.step_type

    def _queue_retry(self, step: LearnStep) -> None:
        retry = LearnStep(
            word=step.word,
            step_type=step.step_type,
            prompt=step.prompt,
            options=step.options,
            correct_answer=step.correct_answer,
            verb_form_key=step.verb_form_key,
            attempt=step.attempt + 1,
        )
        if self.retries_appended:
            self.steps.append(retry)
        else:
            self.retry_queue.append(retry)

    def record_step(self, correct: bool) -> None:
        """Record outcome of the current step.

        Wrong steps are retried up to ``MAX_STEP_ATTEMPTS`` total attempts. The
        first retry wave is appended after the main run; a failed retry appends
        its next retry directly to the active session tail, so retry 2 stays in
        the same /learn session without replaying the card.
        """
        step = self.current_step
        if step is None:
            log_user_error(logger, self.user_id, "record_step on finished session")
            return
        word_id = step.word["id"]
        key = self.step_key(step)
        if correct:
            self.word_step_passed.setdefault(word_id, set()).add(key)
        elif step.attempt < MAX_STEP_ATTEMPTS:
            self._queue_retry(step)
        self.current_index += 1
        # Append retries once we've finished the main run.
        if self.current_index >= len(self.steps) and not self.retries_appended:
            self.steps.extend(self.retry_queue)
            self.retry_queue.clear()
            self.retries_appended = True

    def graduated_words(self) -> list[dict]:
        """Words whose required step keys are all marked passed."""
        out: list[dict] = []
        seen: set[int] = set()
        for s in self.steps:
            word_id = s.word["id"]
            if word_id in seen:
                continue
            seen.add(word_id)
            required = self.required_per_word.get(word_id, set())
            passed = self.word_step_passed.get(word_id, set())
            if required and required <= passed:
                out.append(s.word)
        return out


# --- Step generators ---


def _show_prompt(word: dict) -> str:
    """Render the full card for the SHOW step. HTML-escaped, monospace-friendly."""
    pos = word["part_of_speech"]
    lines: list[str] = []
    german_safe = html.escape(word["german"])

    if pos == "n":
        article = word.get("article") or "?"
        plural = word.get("plural") or "—"
        lines.append(f"<b>{html.escape(article)} {german_safe}</b>")
        lines.append(f"plural: {html.escape(plural)}")
    elif pos == "v":
        lines.append(f"<b>{german_safe}</b>")
        partizip = word.get("partizip_ii")
        if partizip:
            lines.append(f"partizip II: {html.escape(partizip)}")
        forms = parse_irregular_forms(word.get("irregular_forms"))
        if forms:
            forms_str = ", ".join(f"{html.escape(k)}: {html.escape(v)}" for k, v in forms.items())
            lines.append(f"forms: {forms_str}")
    else:
        lines.append(f"<b>{german_safe}</b>")

    lines.append(f"= {html.escape(word['translation'])}")
    if word.get("tags"):
        lines.append(f"tags: {html.escape(word['tags'])}")
    return "\n".join(lines)


def _build_show_step(word: dict) -> LearnStep:
    return LearnStep(
        word=word,
        step_type=SHOW,
        prompt=_show_prompt(word),
        options=None,
        correct_answer=None,
    )


def _build_mc_step(word: dict, all_words: list[dict]) -> LearnStep:
    options, correct = multiple_choice_options(word, all_words)
    return LearnStep(
        word=word,
        step_type=MC,
        prompt=f"What does '{german_with_article(word)}' mean?",
        options=options,
        correct_answer=correct,
    )


def _build_typed_step(word: dict) -> LearnStep:
    return LearnStep(
        word=word,
        step_type=TYPED,
        prompt=f"Type in German: {word['translation']}",
        options=None,
        correct_answer=german_with_article(word),
    )


def _build_article_step(word: dict) -> LearnStep:
    return LearnStep(
        word=word,
        step_type=ARTICLE,
        prompt=f"Pick the article for '{word['german']}'",
        options=["der", "die", "das"],
        correct_answer=word["article"],
    )


def _build_plural_step(word: dict) -> LearnStep:
    # German plural article is always "die"; storing it on the answer means the
    # feedback text shows "die Katzen" — reinforcing the article alongside the
    # plural. ``is_correct("plural", ...)`` accepts user input either with or
    # without the leading "die ", so this is display-only enrichment.
    return LearnStep(
        word=word,
        step_type=PLURAL,
        prompt=f"Type the plural of '{german_with_article(word)}'",
        options=None,
        correct_answer=f"die {word['plural']}",
    )


def _build_partizip_step(word: dict) -> LearnStep:
    return LearnStep(
        word=word,
        step_type=PARTIZIP,
        prompt=f"Type the Partizip II for: {word['translation']}",
        options=None,
        correct_answer=word["partizip_ii"],
    )


def _build_verb_form_steps(word: dict) -> list[LearnStep]:
    forms = parse_irregular_forms(word.get("irregular_forms")) or {}
    usable = [(k, v) for k, v in forms.items() if v]
    random.shuffle(usable)
    picked = usable[:LEARN_VERB_FORMS_COUNT]
    return [
        LearnStep(
            word=word,
            step_type=VERB_FORM,
            prompt=f"Type the '{k}' form of '{word['german']}'",
            options=None,
            correct_answer=v,
            verb_form_key=k,
        )
        for k, v in picked
    ]


def _interleave_steps(per_word: list[list[LearnStep]]) -> list[LearnStep]:
    """Round-robin across words with randomness: each round emits one step from
    every still-non-empty word in a freshly shuffled order. Per-word step order
    (SHOW → MC → TYPED → extras) is preserved because we only pop the head of
    each word's queue.

    With ≥2 words, no two consecutive steps will be from the same word — the
    intra-round shuffle handles within-round variance, and we swap the first
    pick of each new round if it would collide with the previous round's last
    pick. (With a single word, back-to-back is unavoidable, but then there's no
    other word to interleave with.)
    """
    queues = [list(q) for q in per_word if q]
    out: list[LearnStep] = []
    last_word_id: int | None = None
    while any(queues):
        active = [q for q in queues if q]
        order = list(range(len(active)))
        random.shuffle(order)  # noqa: S311
        if last_word_id is not None and len(order) > 1:
            if active[order[0]][0].word["id"] == last_word_id:
                order[0], order[1] = order[1], order[0]
        for i in order:
            step = active[i].pop(0)
            out.append(step)
            last_word_id = step.word["id"]
        queues = [q for q in queues if q]
    return out


def build_session(user_id: int, words: list[dict], all_words: list[dict]) -> LearnSession:
    """Build a learning session: per-word massed drill (show → MC → typed → extras),
    with steps interleaved across words so the same word doesn't repeat back-to-back
    when more than one word is being learned in the session."""
    per_word_steps: list[list[LearnStep]] = []
    required: dict[int, set[str]] = {}

    for w in words:
        word_id = w["id"]
        word_required: set[str] = set()
        word_steps: list[LearnStep] = []

        word_steps.append(_build_show_step(w))
        word_required.add(SHOW)

        word_steps.append(_build_mc_step(w, all_words))
        word_required.add(MC)

        word_steps.append(_build_typed_step(w))
        word_required.add(TYPED)

        if w["part_of_speech"] == "n":
            if w.get("article"):
                word_steps.append(_build_article_step(w))
                word_required.add(ARTICLE)
            if w.get("plural") and w["plural"].strip():
                word_steps.append(_build_plural_step(w))
                word_required.add(PLURAL)
        elif w["part_of_speech"] == "v":
            if w.get("partizip_ii") and w["partizip_ii"].strip():
                word_steps.append(_build_partizip_step(w))
                word_required.add(PARTIZIP)

        for vs in _build_verb_form_steps(w):
            word_steps.append(vs)
            word_required.add(f"{VERB_FORM}:{vs.verb_form_key}")

        per_word_steps.append(word_steps)
        required[word_id] = word_required

    steps = _interleave_steps(per_word_steps)

    log_user_action(
        logger,
        user_id,
        f"Learn session created: {len(words)} word(s), {len(steps)} step(s)",
    )
    return LearnSession(user_id=user_id, steps=steps, required_per_word=required)


def check_answer(step: LearnStep, user_answer: str) -> bool:
    """Validate an answer for a step. SHOW always passes; everything else
    delegates to ``bot.questions.is_correct``."""
    if step.step_type == SHOW:
        return True
    return is_correct(step.step_type, user_answer, step.correct_answer or "")


# --- Graduation ---


async def apply_graduations(conn, session: LearnSession) -> int:
    """For each fully-passed word, seed one word-level SM-2 state and history.
    Returns the number of graduations.

    Quiz history keeps the actual prompt types for stats/debugging, but the
    scheduling state is intentionally per word.
    """
    graduated = session.graduated_words()
    user_id = session.user_id
    await conn.execute("BEGIN")
    try:
        for w_idx, word in enumerate(graduated):
            sp = f"g{w_idx}"
            await conn.execute(f"SAVEPOINT {sp}")
            try:
                row = await get_sm2_state(conn, user_id, word["id"], WORD_REVIEW_STATE)
                new_state = calculate_sm2(sm2_from_db(row, user_id), QUALITY_CORRECT)
                await upsert_sm2_state(
                    conn,
                    user_id,
                    word["id"],
                    WORD_REVIEW_STATE,
                    new_state.easiness_factor,
                    new_state.interval,
                    new_state.repetitions,
                    new_state.correct_count,
                    new_state.next_review,
                    last_quality=QUALITY_CORRECT,
                    commit=False,
                )
                for qt in get_quiz_types_for_word(word):
                    await add_quiz_history(
                        conn,
                        user_id,
                        word["id"],
                        qt,
                        correct=True,
                        source="learn",
                        commit=False,
                    )
                await conn.execute(f"RELEASE SAVEPOINT {sp}")
            except Exception:
                await conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                await conn.execute(f"RELEASE SAVEPOINT {sp}")
                log_user_error(logger, user_id, f"Failed to graduate word_id={word['id']}")
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    log_user_action(logger, user_id, f"Learn session: graduated {len(graduated)} word(s)")
    return len(graduated)


def format_summary(session: LearnSession) -> str:
    """End-of-session summary with graduated/needs-more lists. HTML-escaped."""
    graduated = session.graduated_words()
    graduated_ids = {w["id"] for w in graduated}

    seen: set[int] = set()
    needs_more: list[dict] = []
    for s in session.steps:
        wid = s.word["id"]
        if wid in seen:
            continue
        seen.add(wid)
        if wid not in graduated_ids:
            needs_more.append(s.word)

    lines = [f"<b>Learning complete.</b> Graduated {len(graduated)}/{len(seen)} word(s)."]
    if graduated:
        lines.append("\n<b>Graduated</b> (now eligible for /quiz):")
        for w in graduated:
            lines.append(
                f"  + {html.escape(german_with_article(w))} — {html.escape(w['translation'])}"
            )
    if needs_more:
        lines.append("\n<b>Needs more work</b> (will return in next /learn):")
        for w in needs_more:
            lines.append(
                f"  - {html.escape(german_with_article(w))} — {html.escape(w['translation'])}"
            )
    return "\n".join(lines)
