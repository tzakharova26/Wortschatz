"""Pure-function line parsers for the ``/add`` input format.

Kept separate from the conversation handler so the parsing logic is unit-
testable without the Telegram surface, and so /add stays readable.
"""

from __future__ import annotations

import html

_NO_PLURAL_MARKERS = {"-", "—", "none", "no", "kein", "keine", "нет"}

_FORM_KEY_ALIASES = {
    "p": "partizip_ii",
    "partizip": "partizip_ii",
    "partizip_ii": "partizip_ii",
    "partizipii": "partizip_ii",
    "pr": "preteritum",
    "pret": "preteritum",
    "preteritum": "preteritum",
    "praeteritum": "preteritum",
    "pr_ich": "preteritum_ich",
    "pret_ich": "preteritum_ich",
    "preteritum_ich": "preteritum_ich",
    "praeteritum_ich": "preteritum_ich",
    "pr_du": "preteritum_du",
    "pret_du": "preteritum_du",
    "preteritum_du": "preteritum_du",
    "praeteritum_du": "preteritum_du",
    "pr_er": "preteritum_er",
    "pret_er": "preteritum_er",
    "preteritum_er": "preteritum_er",
    "praeteritum_er": "preteritum_er",
    "pr_sie_es": "preteritum_er",
    "pr_es": "preteritum_er",
    "pr_wir": "preteritum_wir",
    "pret_wir": "preteritum_wir",
    "preteritum_wir": "preteritum_wir",
    "praeteritum_wir": "preteritum_wir",
    "pr_ihr": "preteritum_ihr",
    "pret_ihr": "preteritum_ihr",
    "preteritum_ihr": "preteritum_ihr",
    "praeteritum_ihr": "preteritum_ihr",
    "pr_sie": "preteritum_sie",
    "pret_sie": "preteritum_sie",
    "preteritum_sie": "preteritum_sie",
    "praeteritum_sie": "preteritum_sie",
    "ich": "ich",
    "du": "du",
    "er": "er",
    "sie": "er",
    "es": "er",
}


def _split_form_field(field: str) -> tuple[str, str] | None:
    for sep in ("=", ":"):
        if sep in field:
            key, value = field.split(sep, 1)
            key = _FORM_KEY_ALIASES.get(key.strip().lower().replace("-", "_"))
            value = value.strip()
            if key and value:
                return key, value
    return None


def _parse_form_fields(fields: list[str]) -> tuple[dict | None, str]:
    forms: dict[str, str] = {}
    translation_parts: list[str] = []
    translation_started = False
    for field in fields:
        parsed = None if translation_started else _split_form_field(field)
        if parsed is None:
            translation_started = True
            translation_parts.append(field)
            continue
        key, value = parsed
        forms[key] = value
    return (forms or None), " ".join(translation_parts).strip()


def _parse_noun_line(parts: list[str], safe_line: str) -> tuple[dict | None, str | None]:
    if len(parts) < 5:
        return None, f"Noun needs: n article word plural translation: <code>{safe_line}</code>"
    plural = None if parts[3].strip().lower() in _NO_PLURAL_MARKERS else parts[3]
    return {
        "part_of_speech": "n",
        "german": parts[2],
        "article": parts[1],
        "plural": plural,
        "irregular_forms": None,
        "translation": " ".join(parts[4:]),
    }, None


def _parse_verb_line(
    parts: list[str], is_irregular: bool, safe_line: str, is_pipe: bool
) -> tuple[dict | None, str | None]:
    label = "vi" if is_irregular else "v"

    if is_pipe:
        if len(parts) < 3:
            return None, (
                f"{label} needs: {label} | infinitive | translation: <code>{safe_line}</code>"
            )
        if is_irregular:
            # Legacy compact vi pipe format:
            # vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive
            if len(parts) >= 7 and not _split_form_field(parts[2]):
                irregular_forms = {
                    "partizip_ii": parts[2],
                    "ich": parts[3],
                    "du": parts[4],
                    "er": parts[5],
                }
                translation = " ".join(parts[6:]).strip()
            else:
                irregular_forms, translation = _parse_form_fields(parts[2:])
                if not irregular_forms:
                    return None, f"vi needs irregular forms: <code>{safe_line}</code>"
        else:
            irregular_forms, translation = _parse_form_fields(parts[2:])
        if not translation:
            return None, f"{label} missing translation: <code>{safe_line}</code>"
    else:
        if len(parts) < 3:
            return None, f"{label} needs: {label} infinitive translation: <code>{safe_line}</code>"
        remaining = parts[2:]
        if is_irregular and len(parts) >= 7 and not _split_form_field(parts[2]):
            # Legacy positional vi format, with one- or two-token Partizip II.
            if parts[2] in ("ist", "hat"):
                if len(parts) < 8:
                    return None, f"{label} with ist/hat needs more fields: <code>{safe_line}</code>"
                partizip_ii = f"{parts[2]} {parts[3]}"
                remaining = parts[4:]
            else:
                partizip_ii = parts[2]
                remaining = parts[3:]
            if len(remaining) < 4:
                return None, f"vi needs forms and translation: <code>{safe_line}</code>"
            irregular_forms = {
                "partizip_ii": partizip_ii,
                "ich": remaining[0],
                "du": remaining[1],
                "er": remaining[2],
            }
            translation = " ".join(remaining[3:])
        else:
            irregular_forms, translation = _parse_form_fields(remaining)
            if is_irregular and not irregular_forms:
                return None, f"vi needs irregular forms: <code>{safe_line}</code>"
            if not translation:
                return None, f"{label} missing translation: <code>{safe_line}</code>"

    return {
        "part_of_speech": "v",
        "german": parts[1],
        "article": None,
        "plural": None,
        "irregular_forms": irregular_forms,
        "translation": translation,
    }, None


def _parse_simple_line(
    pos: str, parts: list[str], safe_line: str
) -> tuple[dict | None, str | None]:
    """Parse adj, adv, prep, and phrase lines."""
    if len(parts) < 3:
        return None, f"{pos} needs: {pos} word translation: <code>{safe_line}</code>"
    return {
        "part_of_speech": pos,
        "german": parts[1],
        "article": None,
        "plural": None,
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
    if pos == "phr":
        pos = "phrase"
    if pos == "n":
        return _parse_noun_line(parts, safe_line)
    if pos in ("v", "vi"):
        return _parse_verb_line(
            parts, is_irregular=(pos == "vi"), safe_line=safe_line, is_pipe=is_pipe
        )
    if pos in ("adj", "adv", "prep", "phrase"):
        return _parse_simple_line(pos, parts, safe_line)

    safe_pos = html.escape(pos)
    return None, f"Unknown part of speech '{safe_pos}': <code>{safe_line}</code>"
