QUIZ_SESSION_SIZE = 7
QUIZ_MAX_SIZE = 50  # upper bound on user-requested quiz size
QUIZ_TEMPERATURE = 0.3
LIST_MAX_WORDS = 40

QUIZ_TYPE_WEIGHTS: dict[str, float] = {
    "translate": 1.0,
    "verb_forms": 0.9,
    "multiple_choice": 0.6,
    "article": 0.5,
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
