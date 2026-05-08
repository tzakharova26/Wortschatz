"""Pure-function line parsers for the ``/add`` input format.

Kept separate from the conversation handler so the parsing logic is unit-
testable without the Telegram surface, and so /add stays readable.
"""

from __future__ import annotations

import html


def _parse_noun_line(parts: list[str], safe_line: str) -> tuple[dict | None, str | None]:
    if len(parts) < 5:
        return None, f"Noun needs: n article word plural translation: <code>{safe_line}</code>"
    return {
        "part_of_speech": "n",
        "german": parts[2],
        "article": parts[1],
        "plural": parts[3],
        "partizip_ii": None,
        "irregular_forms": None,
        "translation": " ".join(parts[4:]),
    }, None


def _parse_verb_line(
    parts: list[str], is_irregular: bool, safe_line: str, is_pipe: bool
) -> tuple[dict | None, str | None]:
    label = "vi" if is_irregular else "v"

    if is_pipe:
        # With pipe, partizip_ii is always one field (may contain "ist gefahren" inside)
        min_fields = 7 if is_irregular else 4
        if len(parts) < min_fields:
            if is_irregular:
                return None, (
                    "vi needs: vi | infinitive | partizip_ii | ich | du | er | translation: "
                    f"<code>{safe_line}</code>"
                )
            return None, (
                f"v needs: v | infinitive | partizip_ii | translation: <code>{safe_line}</code>"
            )
        partizip_ii = parts[2]
        if is_irregular:
            irregular_forms = {
                "ich": parts[3],
                "du": parts[4],
                "er": parts[5],
            }
            translation = " ".join(parts[6:])
        else:
            irregular_forms = None
            translation = " ".join(parts[3:])
    else:
        min_required = 7 if is_irregular else 4
        if len(parts) < min_required:
            if is_irregular:
                return None, (
                    "vi needs: vi infinitive partizip_ii ich du er translation: "
                    f"<code>{safe_line}</code>"
                )
            return None, f"v needs: v infinitive partizip_ii translation: <code>{safe_line}</code>"

        # partizip_ii is "ist X" / "hat X" (2 tokens) or a single token
        if parts[2] in ("ist", "hat"):
            if len(parts) < min_required + 1:
                return None, f"{label} with ist/hat needs more fields: <code>{safe_line}</code>"
            partizip_ii = f"{parts[2]} {parts[3]}"
            remaining = parts[4:]
        else:
            partizip_ii = parts[2]
            remaining = parts[3:]

        if is_irregular:
            if len(remaining) < 4:
                return None, f"vi needs ich, du, er, translation: <code>{safe_line}</code>"
            irregular_forms = {
                "ich": remaining[0],
                "du": remaining[1],
                "er": remaining[2],
            }
            translation = " ".join(remaining[3:])
        else:
            if not remaining:
                return None, f"v missing translation: <code>{safe_line}</code>"
            irregular_forms = None
            translation = " ".join(remaining)

    return {
        "part_of_speech": "v",
        "german": parts[1],
        "article": None,
        "plural": None,
        "partizip_ii": partizip_ii,
        "irregular_forms": irregular_forms,
        "translation": translation,
    }, None


def _parse_simple_line(
    pos: str, parts: list[str], safe_line: str
) -> tuple[dict | None, str | None]:
    """Parse adj, adv, prep lines."""
    if len(parts) < 3:
        return None, f"{pos} needs: {pos} word translation: <code>{safe_line}</code>"
    return {
        "part_of_speech": pos,
        "german": parts[1],
        "article": None,
        "plural": None,
        "partizip_ii": None,
        "irregular_forms": None,
        "translation": " ".join(parts[2:]),
    }, None


def _parse_word_line(line: str) -> tuple[dict | None, str | None]:
    """Parse a single word line. Returns (word_dict, error_message).

    Two separator styles are supported per line, auto-detected:
      - Space-separated (positional)
      - Pipe-separated: each "|" delimits a semantic field; fields may contain spaces
    """
    line = line.strip()
    if not line:
        return None, None

    safe_line = html.escape(line)
    is_pipe = "|" in line
    if is_pipe:
        parts = [p.strip() for p in line.split("|") if p.strip()]
    else:
        parts = line.split()

    if len(parts) < 3:
        return None, f"Too few fields: <code>{safe_line}</code>"

    pos = parts[0].lower()
    if pos == "n":
        return _parse_noun_line(parts, safe_line)
    if pos in ("v", "vi"):
        return _parse_verb_line(
            parts, is_irregular=(pos == "vi"), safe_line=safe_line, is_pipe=is_pipe
        )
    if pos in ("adj", "adv", "prep"):
        return _parse_simple_line(pos, parts, safe_line)

    safe_pos = html.escape(pos)
    return None, f"Unknown part of speech '{safe_pos}': <code>{safe_line}</code>"
