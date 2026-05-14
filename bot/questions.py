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


def _tag_set(word: dict) -> set[str]:
    return {tag.strip() for tag in (word.get("tags") or "").split(",") if tag.strip()}


def german_with_article(word: dict) -> str:
    """Render 'article german' for nouns with an article, else just the german word."""
    if word.get("part_of_speech") == "n" and word.get("article"):
        return f"{word['article']} {word['german']}"
    return word["german"]


def multiple_choice_options(word: dict, all_words: list[dict]) -> tuple[list[str], str]:
    """Build options for a multiple-choice prompt.

    Wrong distractors prefer words that share at least one tag AND the same
    POS. If fewer than 3 exist, selection falls back through same-POS words,
    then same-tag words with a different POS, then the rest of the vocabulary.
    Pools are shuffled independently and concatenated so the higher-priority
    candidates are exhausted first.

    Returns ``(options, correct_answer)`` where ``correct_answer`` is the
    word's translation. Options are shuffled before return.
    """
    pos = word["part_of_speech"]
    word_id = word["id"]
    tags = _tag_set(word)
    same_tag_same_pos: list[dict] = []
    same_pos: list[dict] = []
    same_tag_other_pos: list[dict] = []
    other: list[dict] = []

    for candidate in all_words:
        if candidate["id"] == word_id:
            continue
        candidate_tags = _tag_set(candidate)
        shares_tag = bool(tags and candidate_tags.intersection(tags))
        same_part = candidate["part_of_speech"] == pos
        if shares_tag and same_part:
            same_tag_same_pos.append(candidate)
        elif same_part:
            same_pos.append(candidate)
        elif shares_tag:
            same_tag_other_pos.append(candidate)
        else:
            other.append(candidate)

    for candidates in (same_tag_same_pos, same_pos, same_tag_other_pos, other):
        random.shuffle(candidates)
    pool = same_tag_same_pos + same_pos + same_tag_other_pos + other

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
