import html
import random
from dataclasses import dataclass, field
from datetime import datetime

from bot.config import QUIZ_TEMPERATURE, QUIZ_TYPE_WEIGHTS
from bot.database import (
    add_quiz_history,
    get_quiz_types_for_word,
    get_sm2_state,
    parse_irregular_forms,
    upsert_sm2_state,
)
from bot.logging_config import get_logger, log_user_action, log_user_error, log_user_warning
from bot.sm2 import calculate_sm2, sm2_from_db
from bot.umlaut import answers_match

logger = get_logger(__name__)


def german_with_article(word: dict) -> str:
    """Return 'article german' for nouns with articles, else just 'german'."""
    if word.get("part_of_speech") == "n" and word.get("article"):
        return f"{word['article']} {word['german']}"
    return word["german"]


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
        quiz_type = select_quiz_type(word)
        question = generate_question(word, quiz_type, all_words)
        self.questions.append(question)

    @property
    def score(self) -> tuple[int, int]:
        """Return (correct_count, total). Misspells are excluded from both counts."""
        scored = [r for r in self.results if r is not None]
        correct = sum(1 for _, c in scored if c)
        return correct, len(scored)


def _word_score(word: dict, now: datetime, temperature: float) -> float:
    """Compute a word's selection score based on days since last review.

    Higher score = more likely to be selected. Never-reviewed words get max priority.
    Formula: (days_since_last_review + 1) ^ (1 / temperature)
    """
    next_review_str = word.get("earliest_review") or word.get("next_review")
    if not next_review_str or next_review_str == "1970-01-01":
        days_since = 365  # never reviewed = high priority
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
    pos = word["part_of_speech"]
    word_id = word["id"]

    # Collect wrong options: prefer same POS, then any POS
    same_pos = [w for w in all_words if w["part_of_speech"] == pos and w["id"] != word_id]
    other = [w for w in all_words if w["part_of_speech"] != pos and w["id"] != word_id]

    wrong_pool = same_pos + other
    random.shuffle(wrong_pool)
    wrong_translations = []
    seen = {word["translation"].lower()}
    for w in wrong_pool:
        t = w["translation"]
        if t.lower() not in seen:
            wrong_translations.append(t)
            seen.add(t.lower())
        if len(wrong_translations) >= 3:
            break

    options = [word["translation"]] + wrong_translations
    random.shuffle(options)

    return QuizQuestion(
        word=word,
        quiz_type="multiple_choice",
        prompt=f"What does '{german_with_article(word)}' mean?",
        options=options,
        correct_answer=word["translation"],
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
        return QuizSession(user_id=user_id, questions=[])

    if size is None:
        size = len(due_words)

    questions = []
    for i in range(size):
        word = due_words[i % len(due_words)]
        quiz_type = select_quiz_type(word, temperature=temperature, now=now)
        questions.append(generate_question(word, quiz_type, all_words))

    quiz_types_used = [q.quiz_type for q in questions]
    log_user_action(
        logger,
        user_id,
        f"Quiz session created: {len(questions)} questions, types={quiz_types_used}",
    )
    return QuizSession(user_id=user_id, questions=questions)


def check_answer(question: QuizQuestion, user_answer: str) -> bool:
    """Check if the user's answer is correct."""
    if not user_answer or not user_answer.strip():
        return False
    if not question.correct_answer:
        log_user_warning(
            logger,
            question.word.get("user_id", 0),
            f"Question for '{question.word['german']}' has no correct_answer",
        )
        return False
    if question.quiz_type in ("multiple_choice", "article"):
        return user_answer.strip().lower() == question.correct_answer.strip().lower()
    return answers_match(user_answer, question.correct_answer)


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
        else:
            lines.append(f"{mark} {german_safe} — {translation_safe}")
    return "\n".join(lines)


async def apply_results(conn, session: QuizSession) -> int:
    """Apply session results to SM-2 state and quiz history.

    Skips misspells (None entries). Returns the number of questions whose update
    failed; the caller decides how to surface that to the user.
    """
    user_id = session.user_id
    failures = 0
    for i, question in enumerate(session.questions):
        if i >= len(session.results):
            break
        result = session.results[i]
        if result is None:
            continue
        quality, correct = result
        word_id = question.word["id"]
        quiz_type = question.quiz_type
        try:
            row = await get_sm2_state(conn, user_id, word_id, quiz_type)
            new_state = calculate_sm2(sm2_from_db(row, user_id), quality)
            await upsert_sm2_state(
                conn,
                user_id,
                word_id,
                quiz_type,
                new_state.easiness_factor,
                new_state.interval,
                new_state.repetitions,
                new_state.correct_count,
                new_state.next_review,
            )
            await add_quiz_history(conn, user_id, word_id, quiz_type, correct)
        except Exception:
            failures += 1
            log_user_error(logger, user_id, f"Failed to apply quiz result for word_id={word_id}")
    return failures
