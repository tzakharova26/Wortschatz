import html
import random
from dataclasses import dataclass, field
from datetime import datetime

from bot.config import MAX_QUIZ_SESSION_MULTIPLIER, QUIZ_TEMPERATURE, QUIZ_TYPE_WEIGHTS
from bot.database import (
    WORD_REVIEW_STATE,
    add_quiz_history,
    get_quiz_types_for_word,
    get_sm2_state,
    parse_irregular_forms,
    upsert_sm2_state,
)
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning
from bot.questions import (
    german_with_article,
    is_correct,
    multiple_choice_options,
)
from bot.sm2 import calculate_sm2, sm2_from_db

logger = get_logger(__name__)


# Backward-compat re-export for tests / external callers that imported this
# from bot.quiz before it moved to bot.questions.
__all__ = [
    "QuizQuestion",
    "QuizSession",
    "apply_results",
    "build_quiz_session",
    "check_answer",
    "format_summary",
    "generate_question",
    "german_with_article",
    "select_quiz_type",
]


@dataclass
class QuizQuestion:
    word: dict
    quiz_type: str
    prompt: str
    options: list[str] | None  # for multiple_choice / article buttons
    correct_answer: str
    verb_form_key: str | None = None  # "du", "er" etc. for verb_forms


@dataclass
class QuizSession:
    user_id: int
    questions: list[QuizQuestion]
    current_index: int = 0
    max_questions: int | None = None
    # results aligned with questions: None for misspell (skipped), (quality, correct) otherwise
    results: list[tuple[int, bool] | None] = field(default_factory=list)

    @property
    def is_finished(self) -> bool:
        return self.current_index >= len(self.questions)

    @property
    def current_question(self) -> QuizQuestion | None:
        if self.is_finished:
            return None
        return self.questions[self.current_index]

    def record_result(self, quality: int, correct: bool) -> None:
        if self.is_finished:
            log_user_warning(logger, self.user_id, "record_result called on finished session")
            return
        if not 0 <= quality <= 5:
            log_user_warning(logger, self.user_id, f"Invalid quality={quality}, clamping to 0-5")
            quality = max(0, min(5, quality))
        self.results.append((quality, correct))
        self.current_index += 1

    def record_misspell(self) -> None:
        """Record a misspell (skipped, no SM-2 update). Question is repeated at end."""
        if self.is_finished:
            log_user_warning(logger, self.user_id, "record_misspell called on finished session")
            return
        self.results.append(None)
        self.current_index += 1

    def add_misspell_question(self, word: dict, all_words: list[dict]) -> None:
        """Re-add a word with a freshly selected quiz type at the end."""
        if self.max_questions is not None and len(self.questions) >= self.max_questions:
            log_user_warning(
                logger,
                self.user_id,
                f"Misspell repeat limit reached: questions={len(self.questions)}, "
                f"limit={self.max_questions}",
            )
            return
        quiz_type = select_quiz_type(word)
        question = generate_question(word, quiz_type, all_words)
        self.questions.append(question)

    @property
    def can_add_misspell_question(self) -> bool:
        return self.max_questions is None or len(self.questions) < self.max_questions

    @property
    def score(self) -> tuple[int, int]:
        """Return (correct_count, total). Misspells are excluded from both counts."""
        scored = [r for r in self.results if r is not None]
        correct = sum(1 for _, c in scored if c)
        return correct, len(scored)


def _word_score(word: dict, now: datetime, temperature: float) -> float:
    """Compute a word's selection score based on days since last review.

    Higher score = more likely to be selected. Never-reviewed words (no SM-2
    row, no key at all) get max priority.
    Formula: (days_since_last_review + 1) ^ (1 / temperature)
    """
    next_review_str = word.get("earliest_review") or word.get("next_review")
    # No key at all = direct call from a test or a never-reviewed word path.
    # The ``'1970-01-01'`` SQL COALESCE sentinel that used to live here is dead:
    # ``get_due_words`` filters those rows via ``_NOT_LEARNING_CLAUSE`` before
    # they reach this function.
    if not next_review_str:
        days_since = 365
    else:
        try:
            next_review = datetime.fromisoformat(next_review_str)
            days_since = max(0, (now - next_review).days)
        except (ValueError, TypeError):
            log_user_warning(
                logger,
                word.get("user_id", 0),
                f"Invalid review date '{next_review_str}' for word '{word.get('german')}'",
            )
            days_since = 365

    if temperature <= 0:
        temperature = 0.01
    return (days_since + 1) ** (1 / temperature)


def _weighted_word_order(
    words: list[dict],
    now: datetime,
    temperature: float,
) -> list[dict]:
    """Return words in weighted-random order, without replacement.

    More-overdue words remain more likely to appear early, but equally due
    words no longer produce the same session order every time.
    """
    remaining = list(words)
    ordered: list[dict] = []
    while remaining:
        weights = [_word_score(w, now, temperature) for w in remaining]
        index = random.choices(range(len(remaining)), weights=weights, k=1)[0]  # noqa: S311
        ordered.append(remaining.pop(index))
    return ordered


def select_quiz_type(
    word: dict,
    temperature: float = QUIZ_TEMPERATURE,
    weights: dict[str, float] | None = None,
    now: datetime | None = None,
) -> str:
    """Select a quiz type for a word using temperature-weighted random selection.

    The base quiz type weights are scaled by the word's recency score:
    final_weight = base_weight * (days_since_last_review + 1) ^ (1 / temperature)
    """
    if weights is None:
        weights = QUIZ_TYPE_WEIGHTS
    if now is None:
        now = datetime.now()

    applicable = get_quiz_types_for_word(word)
    word_multiplier = _word_score(word, now, temperature)
    type_weights = [weights.get(qt, 0.5) * word_multiplier for qt in applicable]
    return random.choices(applicable, weights=type_weights, k=1)[0]  # noqa: S311


def generate_question(
    word: dict,
    quiz_type: str,
    all_words: list[dict],
) -> QuizQuestion:
    """Generate a single quiz question."""
    if quiz_type == "translate":
        return _generate_translate(word)
    elif quiz_type == "multiple_choice":
        return _generate_multiple_choice(word, all_words)
    elif quiz_type == "article":
        return _generate_article(word)
    elif quiz_type == "verb_forms":
        return _generate_verb_forms(word)
    elif quiz_type == "partizip":
        return _generate_partizip(word)
    elif quiz_type == "plural":
        return _generate_plural(word)
    else:
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Unknown quiz type '{quiz_type}', falling back to translate",
        )
        return _generate_translate(word)


def _generate_translate(word: dict) -> QuizQuestion:
    """Translation -> German: show translation, user types German word."""
    return QuizQuestion(
        word=word,
        quiz_type="translate",
        prompt=f"Translate to German: {word['translation']}",
        options=None,
        correct_answer=german_with_article(word),
    )


def _generate_multiple_choice(word: dict, all_words: list[dict]) -> QuizQuestion:
    """German -> Translation: show German word, pick translation from options."""
    options, correct = multiple_choice_options(word, all_words)
    return QuizQuestion(
        word=word,
        quiz_type="multiple_choice",
        prompt=f"What does '{german_with_article(word)}' mean?",
        options=options,
        correct_answer=correct,
    )


def _generate_article(word: dict) -> QuizQuestion:
    """Article quiz: show noun, pick der/die/das."""
    article = word.get("article")
    if not article:
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Article quiz for word '{word['german']}' without article, "
            "falling back to translate",
        )
        return _generate_translate(word)
    return QuizQuestion(
        word=word,
        quiz_type="article",
        prompt=f"What is the article for '{word['german']}'?",
        options=["der", "die", "das"],
        correct_answer=article,
    )


def _generate_plural(word: dict) -> QuizQuestion:
    """Plural quiz (nouns only): show the singular with article, user types the plural."""
    plural = word.get("plural")
    if not plural or not plural.strip():
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Plural quiz for '{word['german']}' without plural, falling back to translate",
        )
        return _generate_translate(word)
    # Same article-on-display trick as ``learn._build_plural_step``: store the
    # answer with the "die" prefix so feedback/summary lines show the article,
    # while the matcher (``is_correct("plural", ...)``) accepts input either
    # with or without it.
    return QuizQuestion(
        word=word,
        quiz_type="plural",
        prompt=f"What is the plural of '{german_with_article(word)}'?",
        options=None,
        correct_answer=f"die {plural}",
    )


def _generate_verb_forms(word: dict) -> QuizQuestion:
    """Verb forms quiz: show infinitive, ask for a specific form."""
    forms = parse_irregular_forms(word.get("irregular_forms"))
    if not forms:
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Verb forms quiz for '{word['german']}' without irregular forms, "
            "falling back to translate",
        )
        return _generate_translate(word)

    form_key = random.choice(list(forms.keys()))  # noqa: S311
    correct = forms[form_key]
    if not correct:
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Empty form value for '{form_key}' in word '{word['german']}', "
            "falling back to translate",
        )
        return _generate_translate(word)

    return QuizQuestion(
        word=word,
        quiz_type="verb_forms",
        prompt=f"What is the '{form_key}' form of '{word['german']}'?",
        options=None,
        correct_answer=correct,
        verb_form_key=form_key,
    )


def _generate_partizip(word: dict) -> QuizQuestion:
    """Partizip II quiz: show translation, user types full stored Partizip II."""
    partizip = word.get("partizip_ii")
    if not partizip or not partizip.strip():
        log_user_warning(
            logger,
            word.get("user_id", 0),
            f"Partizip quiz for '{word['german']}' without partizip_ii, falling back to translate",
        )
        return _generate_translate(word)
    return QuizQuestion(
        word=word,
        quiz_type="partizip",
        prompt=f"Type the Partizip II for: {word['translation']}",
        options=None,
        correct_answer=partizip,
    )


def build_quiz_session(
    user_id: int,
    due_words: list[dict],
    all_words: list[dict],
    size: int | None = None,
    now: datetime | None = None,
    temperature: float = QUIZ_TEMPERATURE,
) -> QuizSession:
    """Build a quiz session of `size` questions.

    If size is None, defaults to len(due_words). If due_words has fewer items than
    size, words cycle to fill the session — each repetition gets a freshly weighted
    quiz type, so the same word can show up under different quiz types.
    """
    if now is None:
        now = datetime.now()

    if not due_words:
        log_user_action(logger, user_id, "Quiz session created: 0 questions (no due words)")
        return QuizSession(user_id=user_id, questions=[], max_questions=0)

    if size is None:
        size = len(due_words)

    ordered_words = _weighted_word_order(due_words, now, temperature)
    questions = []
    for i in range(size):
        word = ordered_words[i % len(ordered_words)]
        quiz_type = select_quiz_type(word, temperature=temperature, now=now)
        questions.append(generate_question(word, quiz_type, all_words))

    quiz_types_used = [q.quiz_type for q in questions]
    log_user_action(
        logger,
        user_id,
        f"Quiz session created: {len(questions)} questions, types={quiz_types_used}",
    )
    return QuizSession(
        user_id=user_id,
        questions=questions,
        max_questions=size * MAX_QUIZ_SESSION_MULTIPLIER,
    )


def check_answer(question: QuizQuestion, user_answer: str) -> bool:
    """Check if the user's answer is correct."""
    if not question.correct_answer:
        log_user_warning(
            logger,
            question.word.get("user_id", 0),
            f"Question for '{question.word['german']}' has no correct_answer",
        )
        return False
    return is_correct(question.quiz_type, user_answer, question.correct_answer)


def format_summary(session: QuizSession) -> str:
    """Format the end-of-quiz summary. HTML-safe."""
    correct, total = session.score
    lines = [f"Quiz complete! {correct}/{total} correct\n"]
    for i, question in enumerate(session.questions):
        if i >= len(session.results):
            break
        result = session.results[i]
        if result is None:
            continue  # misspell, skipped
        _, was_correct = result
        mark = "+" if was_correct else "-"
        word = question.word
        german_safe = html.escape(german_with_article(word))
        translation_safe = html.escape(word["translation"])
        if question.quiz_type == "verb_forms" and question.verb_form_key:
            answer_safe = html.escape(question.correct_answer)
            form_safe = html.escape(question.verb_form_key)
            lines.append(f"{mark} {german_safe} ({form_safe}) — {answer_safe}")
        elif question.quiz_type == "partizip":
            answer_safe = html.escape(question.correct_answer)
            lines.append(f"{mark} {german_safe} (Partizip II) — {answer_safe}")
        elif question.quiz_type == "plural":
            answer_safe = html.escape(question.correct_answer)
            lines.append(f"{mark} {german_safe} (plural) — {answer_safe}")
        else:
            lines.append(f"{mark} {german_safe} — {translation_safe}")
    return "\n".join(lines)


async def apply_results(conn, session: QuizSession) -> int:
    """Apply session results to SM-2 state and quiz history.

    Skips misspells (None entries). Returns the number of questions whose update
    failed; the caller decides how to surface that to the user.

    Atomicity: each (sm2_state upsert, quiz_history insert) pair runs inside a
    SAVEPOINT, and the whole batch sits inside one transaction with a single
    final COMMIT. A row-level exception rolls back just that pair; a process
    crash before COMMIT loses the whole batch (clean retry on restart).
    """
    user_id = session.user_id
    failures = 0
    await conn.execute("BEGIN")
    try:
        for i, question in enumerate(session.questions):
            if i >= len(session.results):
                break
            result = session.results[i]
            if result is None:
                continue
            quality, correct = result
            word_id = question.word["id"]
            quiz_type = question.quiz_type
            sp = f"q{i}"
            await conn.execute(f"SAVEPOINT {sp}")
            try:
                row = await get_sm2_state(conn, user_id, word_id, WORD_REVIEW_STATE)
                new_state = calculate_sm2(sm2_from_db(row, user_id), quality)
                await upsert_sm2_state(
                    conn,
                    user_id,
                    word_id,
                    WORD_REVIEW_STATE,
                    new_state.easiness_factor,
                    new_state.interval,
                    new_state.repetitions,
                    new_state.correct_count,
                    new_state.next_review,
                    last_quality=quality,
                    commit=False,
                )
                await add_quiz_history(conn, user_id, word_id, quiz_type, correct, commit=False)
                await conn.execute(f"RELEASE SAVEPOINT {sp}")
            except Exception:
                await conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                await conn.execute(f"RELEASE SAVEPOINT {sp}")
                failures += 1
                log_user_error(
                    logger, user_id, f"Failed to apply quiz result for word_id={word_id}"
                )
        await conn.commit()
    except Exception:
        # Anything outside the per-row savepoints (BEGIN/COMMIT itself) — rollback the
        # whole batch and re-raise so the caller knows nothing landed.
        await conn.rollback()
        raise
    return failures
