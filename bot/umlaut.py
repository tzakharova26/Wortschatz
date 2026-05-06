_REPLACEMENTS = [
    ("ae", "\u00e4"),
    ("oe", "\u00f6"),
    ("ue", "\u00fc"),
    ("Ae", "\u00c4"),
    ("Oe", "\u00d6"),
    ("Ue", "\u00dc"),
    ("ss", "\u00df"),
]

# Words where "ue", "ae", "oe" are NOT umlauts (e.g., "abenteuer", "israel")
# This is a simplified approach — we convert greedily.


def convert_umlauts(text: str) -> str:
    """Convert ASCII umlaut representations to proper Unicode characters.

    ae -> ae, oe -> oe, ue -> ue, ss -> ss (eszett)
    """
    result = text
    for ascii_form, unicode_form in _REPLACEMENTS:
        result = result.replace(ascii_form, unicode_form)
    return result


def normalize_for_comparison(text: str) -> str:
    """Normalize text so both umlaut forms match during comparison.

    Converts to lowercase and replaces umlauts with ASCII equivalents.
    """
    result = text.lower().strip()
    result = result.replace("\u00e4", "ae")
    result = result.replace("\u00f6", "oe")
    result = result.replace("\u00fc", "ue")
    result = result.replace("\u00df", "ss")
    return result


def answers_match(user_answer: str, correct_answer: str) -> bool:
    """Check if user's answer matches the correct answer, tolerating umlaut variations."""
    return normalize_for_comparison(user_answer) == normalize_for_comparison(correct_answer)
