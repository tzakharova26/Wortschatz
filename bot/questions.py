"""Shared building blocks for /quiz (revision) and /learn (acquisition).

Both flows pose the same kinds of questions — show a German word, ask for the
translation, ask for an article / plural / verb form, etc. The session
containers and step semantics differ, but the question-shaped helpers
(distractor pool, formatting, answer comparison) are identical and live here
so neither module has to reach into the other's privates.
"""

from __future__ import annotations

import random

from bot.umlaut import answers_match


def german_with_article(word: dict) -> str:
    """Render 'article german' for nouns with an article, else just the german word."""
    if word.get("part_of_speech") == "n" and word.get("article"):
        return f"{word['article']} {word['german']}"
    return word["german"]


def multiple_choice_options(word: dict, all_words: list[dict]) -> tuple[list[str], str]:
    """Build options for a multiple-choice prompt.

    Wrong distractors prefer same-POS words from the user's vocabulary; if
    fewer than 3 same-POS candidates exist, fall back to other-POS words. The
    two pools are shuffled independently and concatenated (NOT shuffled
    together) so same-POS distractors are exhausted first.

    Returns ``(options, correct_answer)`` where ``correct_answer`` is the
    word's translation. Options are shuffled before return.
    """
    pos = word["part_of_speech"]
    word_id = word["id"]
    same_pos = [w for w in all_words if w["part_of_speech"] == pos and w["id"] != word_id]
    other = [w for w in all_words if w["part_of_speech"] != pos and w["id"] != word_id]
    random.shuffle(same_pos)
    random.shuffle(other)
    pool = same_pos + other

    seen = {word["translation"].lower()}
    distractors: list[str] = []
    for w in pool:
        t = w["translation"]
        if t.lower() not in seen:
            distractors.append(t)
            seen.add(t.lower())
        if len(distractors) >= 3:
            break

    options = [word["translation"], *distractors]
    random.shuffle(options)
    return options, word["translation"]


# Question kinds that compare via case-insensitive exact match on the user's tap.
_BUTTON_KINDS = frozenset({"multiple_choice", "article"})


def _strip_plural_article(text: str) -> str:
    """Drop a leading "die " (case-insensitive) from a plural answer.

    Plural in German always takes "die"; we accept user input both with and
    without it. The stored ``correct_answer`` for plural quizzes/learn-steps
    is "die <plural>" so display lines carry the article — but matching
    must not require the user to type it.
    """
    s = text.strip()
    if s.lower().startswith("die "):
        return s[4:].strip()
    return s


def is_correct(kind: str, user_answer: str, correct_answer: str) -> bool:
    """Compare a user answer to the stored correct answer for a question of
    the given kind. SHOW-style steps never call this — they always pass.

    Button-tap kinds (multiple_choice, article) use case-insensitive exact
    match. Typed kinds (translate, verb_forms, plural) use ``answers_match``,
    which permits ASCII digraphs (ae/oe/ue/ss) but rejects extra umlauts the
    stored answer doesn't have. For ``plural`` an optional leading "die " is
    stripped from both sides before comparison.
    """
    if not user_answer or not user_answer.strip():
        return False
    if not correct_answer:
        return False
    if kind in _BUTTON_KINDS:
        return user_answer.strip().lower() == correct_answer.strip().lower()
    if kind == "plural":
        return answers_match(
            _strip_plural_article(user_answer),
            _strip_plural_article(correct_answer),
        )
    return answers_match(user_answer, correct_answer)
