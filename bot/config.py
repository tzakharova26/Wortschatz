import os

QUIZ_SESSION_SIZE = 7
QUIZ_MAX_SIZE = 50  # upper bound on user-requested quiz size
MAX_QUIZ_SESSION_MULTIPLIER = 2  # misspell repeats cannot grow a session beyond this
QUIZ_TEMPERATURE = 0.3
LIST_MAX_WORDS = 40

# /learn batches are heavier per word (4-5 steps), so cap is lower than /quiz.
# Floor exists so a single session has enough words to interleave meaningfully —
# below ~5 words the round-robin shuffle degenerates into a near-fixed sequence.
LEARN_MIN_SIZE = 5
LEARN_MAX_SIZE = 20

# Safety limits for a small VPS/pet-project deployment.
MAX_USERS = 10
MAX_WORDS_PER_USER = 5000
MAX_ADD_BATCH_SIZE = 50
MAX_ADD_MESSAGE_CHARS = 8000
MAX_GERMAN_LENGTH = 120
MAX_TRANSLATION_LENGTH = 120
MAX_TAGS_PER_WORD = 5
MAX_TAGS_PER_USER = 100
MAX_TAG_LENGTH = 32
MAX_REMINDERS_PER_USER = 10
DB_SIZE_WARNING_MB = 100
DB_SIZE_HARD_LIMIT_MB = 500

OWNER_TG_NICKNAME_ENV = "OWNER_TG_NICKNAME"
OWNER_USER_ID_ENV = "OWNER_USER_ID"
DEFAULT_OWNER_TG_NICKNAME = "tatiana_zakhar"
MAX_OWNER_MESSAGE_CHARS = 2000


def get_owner_tg_nickname() -> str:
    return os.getenv(OWNER_TG_NICKNAME_ENV, DEFAULT_OWNER_TG_NICKNAME).strip()


def get_owner_user_id() -> int | None:
    raw = os.getenv(OWNER_USER_ID_ENV, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


LEARN_START_MESSAGE = (
    "Learning {n} word(s). Each word steps through:\n"
    "  1. See the card  2. Multiple choice  3. Type it\n"
    "  + article and plural (nouns) or Partizip II and verb forms (verbs)\n\n"
    "Wrong steps get up to two retries. A word graduates only after every "
    "step is correct — graduated words become eligible for /quiz."
)

QUIZ_TYPE_WEIGHTS: dict[str, float] = {
    "translate": 1.0,
    "verb_forms": 0.9,
    "partizip": 0.8,
    "multiple_choice": 0.6,
    "article": 0.5,
    "plural": 0.5,
}

# Self-rating quality scores (SM-2 scale 0-5)
QUALITY_BLACKOUT = 0
QUALITY_WRONG = 1
QUALITY_GOOD = 4
QUALITY_EASY = 5

QUIZ_START_MESSAGE = (
    "Quiz time! After each answer, rate how well you knew it:\n\n"
    "If you answered correctly:\n"
    "  Good — correct, normal effort\n"
    "  Easy — correct, effortless\n"
    "  Misspell — knew it but typo (word repeats)\n\n"
    "If you answered incorrectly:\n"
    "  Blackout — no idea at all\n"
    "  Wrong — partially remembered\n"
    "  Misspell — knew it but typo (word repeats)\n"
)
