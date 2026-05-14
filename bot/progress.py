from __future__ import annotations

import html


def _word_label(count: int) -> str:
    return "word" if count == 1 else "words"


def format_learning_overview(overview: dict[str, int], tag: str | None = None) -> str:
    """Format compact learning counts for reminders."""
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    review_words = overview["review_words"]
    total_words = overview["total_words"]

    scope = f" for #{html.escape(tag)}" if tag else ""
    return (
        f"<b>Practice snapshot{scope}</b>\n"
        f"Ready to review: {due} {_word_label(due)}\n"
        f"Waiting to learn: {needs_learning} {_word_label(needs_learning)}\n"
        f"Already in rotation: {review_words}/{total_words} {_word_label(total_words)}"
    )


def format_quiz_intro(overview: dict[str, int], tag: str | None = None) -> str:
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    scope = f" in #{html.escape(tag)}" if tag else ""
    lines = [
        "<b>Ready for a quick review?</b>",
        f"{due} {_word_label(due)}{scope} are ready to practice now.",
    ]
    if needs_learning:
        lines.append(f"{needs_learning} new {_word_label(needs_learning)} are waiting in /learn.")
    lines.append("Let's warm them up.")
    return "\n".join(lines)


def format_stats_queue(overview: dict[str, int]) -> str:
    due = overview["due_review"]
    needs_learning = overview["needs_learning"]
    review_words = overview["review_words"]
    total_words = overview["total_words"]
    return (
        "<b>Learning queue:</b>\n"
        f"  Ready to review: {due} {_word_label(due)}\n"
        f"  Waiting to learn: {needs_learning} {_word_label(needs_learning)}\n"
        f"  In rotation: {review_words}/{total_words} {_word_label(total_words)}"
    )
