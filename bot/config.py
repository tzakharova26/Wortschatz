QUIZ_SESSION_SIZE = 7
QUIZ_MAX_SIZE = 50  # upper bound on user-requested quiz size
QUIZ_TEMPERATURE = 0.3
LIST_MAX_WORDS = 40

# /learn batches are heavier per word (4-5 steps), so cap is lower than /quiz.
# Floor exists so a single session has enough words to interleave meaningfully —
# below ~5 words the round-robin shuffle degenerates into a near-fixed sequence.
LEARN_MIN_SIZE = 5
LEARN_MAX_SIZE = 10

LEARN_START_MESSAGE = (
    "Learning {n} word(s). Each word steps through:\n"
    "  1. See the card  2. Multiple choice  3. Type it\n"
    "  + article and plural (nouns) or two verb forms (irregular verbs)\n\n"
    "Wrong steps are retried at the end. A word graduates only after every "
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
