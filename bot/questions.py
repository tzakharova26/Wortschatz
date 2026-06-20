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

PRETERITUM_PERSON_KEYS = (
    "preteritum_ich",
    "preteritum_du",
    "preteritum_er",
    "preteritum_wir",
    "preteritum_ihr",
    "preteritum_sie",
)
VERB_FORM_ORDER = (
    "partizip_ii",
    "preteritum",
    *PRETERITUM_PERSON_KEYS,
    "ich",
    "du",
    "er",
    "wir",
    "ihr",
    "sie",
)
VERB_FORM_LABELS = {
    "partizip_ii": "Partizip II",
    "preteritum": "Präteritum",
    "preteritum_ich": "Präteritum ich",
    "preteritum_du": "Präteritum du",
    "preteritum_er": "Präteritum er/sie/es",
    "preteritum_wir": "Präteritum wir",
    "preteritum_ihr": "Präteritum ihr",
    "preteritum_sie": "Präteritum sie/Sie",
    "er": "er/sie/es",
    "sie": "sie/Sie",
}

ADJECTIVE_EXAMPLE_QUIZ = "adjective_example"
ADJECTIVE_EXAMPLES = (
    ("der ___ Mann", "e"),
    ("die ___ Frau", "e"),
    ("das ___ Kind", "e"),
    ("ein ___ Mann", "er"),
    ("eine ___ Frau", "e"),
    ("ein ___ Kind", "es"),
    ("Ich sehe den ___ Mann.", "en"),
    ("Wir sprechen mit dem ___ Mann.", "en"),
)

INSEPARABLE_PREFIXES = ("be", "emp", "ent", "er", "ge", "miss", "ver", "zer")
SEPARABLE_PREFIXES = (
    "ab",
    "an",
    "auf",
    "aus",
    "bei",
    "ein",
    "fest",
    "her",
    "hin",
    "los",
    "mit",
    "nach",
    "vor",
    "weg",
    "zu",
    "zurück",
)
REFLEXIVE_FORMS = {
    "ich": "mich",
    "du": "dich",
    "er": "sich",
    "wir": "uns",
    "ihr": "euch",
    "sie": "sich",
}


def verb_form_label(key: str) -> str:
    return VERB_FORM_LABELS.get(key, key)


def _tag_set(word: dict) -> set[str]:
    return {tag.strip() for tag in (word.get("tags") or "").split(",") if tag.strip()}


def german_with_article(word: dict) -> str:
    """Render 'article german' for nouns with an article, else just the german word."""
    if word.get("part_of_speech") == "n" and word.get("article"):
        return f"{word['article']} {word['german']}"
    return word["german"]


def _split_reflexive(infinitive: str) -> tuple[bool, str]:
    word = infinitive.strip()
    prefix = "sich "
    if word.lower().startswith(prefix):
        return True, word[len(prefix) :].strip()
    return False, word


def _split_trailing_phrase(infinitive: str) -> tuple[str, str | None]:
    """Split ``infinitive`` into the conjugated verb head and trailing phrase.

    Examples:
    - ``warten auf`` -> (``warten``, ``auf``)
    - ``freuen auf`` -> (``freuen``, ``auf``)
    - ``aufmachen`` -> (``aufmachen``, None)
    """
    parts = infinitive.strip().split()
    if not parts:
        return "", None
    head = parts[0]
    tail = " ".join(parts[1:]).strip() or None
    return head, tail


def _split_separable(stem: str) -> tuple[str | None, str]:
    prefix = next(
        (p for p in SEPARABLE_PREFIXES if stem.startswith(p) and len(stem) > len(p) + 2),
        None,
    )
    if not prefix:
        return None, stem
    return prefix, stem[len(prefix) :]


def _stem_from_infinitive(word: str) -> tuple[str, str | None]:
    if word.endswith("eln") and len(word) > 3:
        return word[:-2], "eln"
    if word.endswith("ern") and len(word) > 3:
        return word[:-1], "ern"
    if word.endswith("en") and len(word) > 2:
        return word[:-2], "en"
    if word.endswith("n") and len(word) > 1:
        return word[:-1], "n"
    return word, None


def _takes_extra_e(value: str) -> bool:
    if value.endswith(("d", "t")):
        return True
    if len(value) >= 2 and value[-1] in {"m", "n"}:
        return value[-2] not in {"a", "e", "i", "o", "u", "ä", "ö", "ü", "l", "r"}
    return False


def _uses_t_for_du(value: str) -> bool:
    return value.endswith(("s", "ß", "z", "x"))


def regular_partizip_ii(infinitive: str) -> str:
    """Generate the full regular Partizip II answer, including auxiliary.

    The default auxiliary is ``hat``. True ``ist`` verbs and irregular/separable
    edge cases should be stored explicitly with ``p=...`` so they override this
    generated value.
    """
    is_reflexive, phrase = _split_reflexive(infinitive)
    word, _tail = _split_trailing_phrase(phrase)

    if word.endswith("eln") and len(word) > 3:
        stem = word[:-2]
        participle = f"ge{stem}elt"
    else:
        stem, _ending = _stem_from_infinitive(word)
        suffix = "et" if _takes_extra_e(stem) else "t"
        if word.endswith("ieren") or word.startswith(INSEPARABLE_PREFIXES):
            participle = f"{stem}{suffix}"
        else:
            prefix, core_stem = _split_separable(stem)
            if prefix:
                participle = f"{prefix}ge{core_stem}{suffix}"
            else:
                participle = f"ge{stem}{suffix}"
    if is_reflexive:
        return f"hat sich {participle}"
    return f"hat {participle}"


def _attach_present_parts(
    base: str,
    person: str,
    reflexive: bool,
    tail: str | None,
    separable: str | None,
) -> str:
    parts = [base]
    if reflexive:
        parts.append(REFLEXIVE_FORMS[person])
    if tail:
        parts.append(tail)
    if separable:
        parts.append(separable)
    return " ".join(parts)


def regular_verb_forms(infinitive: str) -> dict[str, str]:
    """Best-effort regular German forms for verb-focused revision.

    Stored irregular forms override these generated values. This intentionally
    stays conservative and transparent: it covers common regular verbs well,
    while unusual verbs should store their non-standard forms explicitly.
    """
    reflexive, phrase = _split_reflexive(infinitive)
    word, tail = _split_trailing_phrase(phrase)
    stem, ending = _stem_from_infinitive(word)
    separable, conjugation_stem = _split_separable(stem)

    if ending == "eln":
        present_stem = conjugation_stem + "el"
        return {
            "partizip_ii": regular_partizip_ii(infinitive),
            "ich": _attach_present_parts(
                f"{conjugation_stem}le",
                "ich",
                reflexive,
                tail,
                separable,
            ),
            "du": _attach_present_parts(f"{present_stem}st", "du", reflexive, tail, separable),
            "er": _attach_present_parts(f"{present_stem}t", "er", reflexive, tail, separable),
            "wir": _attach_present_parts(word, "wir", reflexive, tail, separable),
            "ihr": _attach_present_parts(f"{present_stem}t", "ihr", reflexive, tail, separable),
            "sie": _attach_present_parts(word, "sie", reflexive, tail, separable),
        }

    extra_e = _takes_extra_e(conjugation_stem)
    du_suffix = "est" if extra_e else "t" if _uses_t_for_du(conjugation_stem) else "st"
    er_suffix = "et" if extra_e else "t"
    wir_sie = word if not separable else conjugation_stem + (ending or "")
    return {
        "partizip_ii": regular_partizip_ii(infinitive),
        "ich": _attach_present_parts(f"{conjugation_stem}e", "ich", reflexive, tail, separable),
        "du": _attach_present_parts(
            f"{conjugation_stem}{du_suffix}",
            "du",
            reflexive,
            tail,
            separable,
        ),
        "er": _attach_present_parts(
            f"{conjugation_stem}{er_suffix}",
            "er",
            reflexive,
            tail,
            separable,
        ),
        "wir": _attach_present_parts(wir_sie, "wir", reflexive, tail, separable),
        "ihr": _attach_present_parts(
            f"{conjugation_stem}{er_suffix}",
            "ihr",
            reflexive,
            tail,
            separable,
        ),
        "sie": _attach_present_parts(wir_sie, "sie", reflexive, tail, separable),
    }


def adjective_form(adjective: str, ending: str) -> str:
    """Best-effort adjective ending generator for simple example phrases."""
    base = adjective.strip()
    if base.endswith("el") and len(base) > 3:
        base = base[:-2] + "l"
    elif base.lower() == "teuer":
        base = base[:-2] + "r"
    elif base.lower() == "sauer":
        base = base[:-2] + "r"
    elif base.lower() == "hoch":
        base = base[:-1]
    if ending == "e" and base.endswith("e"):
        return base
    return f"{base}{ending}"


def adjective_example_question(adjective: str) -> tuple[str, str]:
    """Return (prompt fragment with blank, expected inflected adjective)."""
    phrase, ending = random.choice(ADJECTIVE_EXAMPLES)  # noqa: S311
    return phrase, adjective_form(adjective, ending)


def all_verb_forms(word: dict, stored_forms: dict | None = None) -> dict[str, tuple[str, bool]]:
    """Return form key -> (value, is_stored_irregular).

    The generated regular forms make regular verbs useful in verb revision,
    while stored values mark the forms that should be prioritized as irregular.
    """
    forms = {key: (value, False) for key, value in regular_verb_forms(word["german"]).items()}
    for key, value in (stored_forms or {}).items():
        if value:
            forms[key] = (value, True)
    ordered = {key: forms[key] for key in VERB_FORM_ORDER if key in forms and forms[key][0]}
    for key, value in forms.items():
        if key not in ordered and value[0]:
            ordered[key] = value
    return ordered


def stored_verb_forms_for_questions(stored_forms: dict | None) -> dict[str, str]:
    """Return stored verb forms ordered for display/questions.

    ``pr=...`` remains the simple single-field Präteritum. If a user also
    stores person-specific Präteritum forms, those keys are shown/asked as
    separate adjustable forms instead of losing that detail.
    """
    forms = {key: value for key, value in (stored_forms or {}).items() if value}
    ordered = {key: forms[key] for key in VERB_FORM_ORDER if key in forms}
    for key, value in forms.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


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
