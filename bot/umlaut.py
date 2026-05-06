_REPLACEMENTS = [
    ("ae", "\u00e4"),
    ("oe", "\u00f6"),
    ("ue", "\u00fc"),
    ("Ae", "\u00c4"),
    ("Oe", "\u00d6"),
    ("Ue", "\u00dc"),
    ("ss", "\u00df"),
]

# Reverse mapping: unicode -> ascii digraph (lowercase only, for comparison)
_EXPAND_MAP = {
    "\u00e4": "ae",
    "\u00f6": "oe",
    "\u00fc": "ue",
    "\u00c4": "ae",
    "\u00d6": "oe",
    "\u00dc": "ue",
    "\u00df": "ss",
}

_SPECIAL_CHARS = set("\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc\u00df")


def convert_umlauts(text: str) -> str:
    """Convert ASCII umlaut representations to proper Unicode characters.

    ae -> ä, oe -> ö, ue -> ü, ss -> ß (eszett)
    """
    result = text
    for ascii_form, unicode_form in _REPLACEMENTS:
        result = result.replace(ascii_form, unicode_form)
    return result


def _expand_special_chars(text: str) -> str:
    """Expand ä→ae, ö→oe, ü→ue, ß→ss for comparison."""
    result = []
    for ch in text:
        if ch in _EXPAND_MAP:
            result.append(_EXPAND_MAP[ch])
        else:
            result.append(ch)
    return "".join(result)


def normalize_for_comparison(text: str) -> str:
    """Normalize text so both umlaut forms match during comparison.

    Converts to lowercase and replaces umlauts with ASCII equivalents.
    """
    return _expand_special_chars(text.lower().strip())


def _has_false_special_chars(user_input: str, stored: str) -> bool:
    """Check if user typed ä/ö/ü/ß where the stored word has plain a/o/u/ss.

    Walk both strings in parallel after expanding to digraphs. For each special
    char in user_input, check if the stored word has the same special char at
    that position.
    """
    u_lower = user_input.lower().strip()
    s_lower = stored.lower().strip()

    # Build position maps: for each char index in the expanded form,
    # track whether the original had a special char at that position.
    def build_special_map(text: str) -> list[bool]:
        result = []
        for ch in text:
            if ch in _EXPAND_MAP:
                expanded = _EXPAND_MAP[ch]
                result.extend([True] * len(expanded))
            else:
                result.append(False)
        return result

    u_map = build_special_map(u_lower)
    s_map = build_special_map(s_lower)

    if len(u_map) != len(s_map):
        return False  # length mismatch handled by the equality check

    for i in range(len(u_map)):
        if u_map[i] and not s_map[i]:
            return True  # user has special char where stored doesn't

    return False


def answers_match(user_answer: str, correct_answer: str) -> bool:
    """Check if user's answer matches, with directional umlaut tolerance.

    Rules:
    - User may simplify: ä→ae, ö→oe, ü→ue, ß→ss (always accepted)
    - User must NOT add special chars where stored word doesn't have them
      (typing ä where stored is a = WRONG, typing ß where stored is ss = WRONG)
    """
    # Step 1: expand both and compare (catches missing umlauts too)
    if normalize_for_comparison(user_answer) != normalize_for_comparison(correct_answer):
        return False

    # Step 2: check user didn't add false special chars
    if _has_false_special_chars(user_answer, correct_answer):
        return False

    return True
