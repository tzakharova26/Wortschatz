from __future__ import annotations

import html

from bot.i18n import normalize_language, word_label


def format_learning_overview(
    overview: dict[str, int], tag: str | None = None, lang: str = "en"
) -> str:
    """Format compact learning counts for reminders."""
    lang = normalize_language(lang)
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    review_words = overview["review_words"]
    total_words = overview["total_words"]

    scope = f" for #{html.escape(tag)}" if tag else ""
    if lang == "ru":
        scope = f" для #{html.escape(tag)}" if tag else ""
        return (
            f"<b>Состояние практики{scope}</b>\n"
            f"Пора повторить: {due} {word_label(due, lang)}\n"
            f"Ждут изучения: {needs_learning} {word_label(needs_learning, lang)}\n"
            f"Уже в повторении: {review_words}/{total_words} {word_label(total_words, lang)}"
        )
    return (
        f"<b>Practice snapshot{scope}</b>\n"
        f"Ready to review: {due} {word_label(due, lang)}\n"
        f"Waiting to learn: {needs_learning} {word_label(needs_learning, lang)}\n"
        f"Already in rotation: {review_words}/{total_words} {word_label(total_words, lang)}"
    )


def format_quiz_intro(overview: dict[str, int], tag: str | None = None, lang: str = "en") -> str:
    lang = normalize_language(lang)
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    scope = f" in #{html.escape(tag)}" if tag else ""
    if lang == "ru":
        scope = f" с тегом #{html.escape(tag)}" if tag else ""
        lines = [
            "<b>Готова к короткому повторению?</b>",
            f"{due} {word_label(due, lang)}{scope} можно повторить сейчас.",
        ]
        if needs_learning:
            lines.append(
                f"{needs_learning} новых {word_label(needs_learning, lang)} ждут в /learn."
            )
        lines.append("Разомнем память.")
        return "\n".join(lines)
    lines = [
        "<b>Ready for a quick review?</b>",
        f"{due} {word_label(due, lang)}{scope} are ready to practice now.",
    ]
    if needs_learning:
        lines.append(
            f"{needs_learning} new {word_label(needs_learning, lang)} are waiting in /learn."
        )
    lines.append("Let's warm them up.")
    return "\n".join(lines)


def format_stats_queue(overview: dict[str, int], lang: str = "en") -> str:
    lang = normalize_language(lang)
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    review_words = overview["review_words"]
    total_words = overview["total_words"]
    if lang == "ru":
        return (
            "<b>Очередь обучения:</b>\n"
            f"  Пора повторить: {due} {word_label(due, lang)}\n"
            f"  Ждут изучения: {needs_learning} {word_label(needs_learning, lang)}\n"
            f"  В повторении: {review_words}/{total_words} {word_label(total_words, lang)}"
        )
    return (
        "<b>Learning queue:</b>\n"
        f"  Ready to review: {due} {word_label(due, lang)}\n"
        f"  Waiting to learn: {needs_learning} {word_label(needs_learning, lang)}\n"
        f"  In rotation: {review_words}/{total_words} {word_label(total_words, lang)}"
    )
