"""Telegram handler layer.

Split into per-flow submodules (add, quiz, learn, simple, reminders) plus
shared helpers (_shared, parsers). This package re-exports the flat surface
that ``bot.main`` and the tests have always imported from ``bot.handlers``,
so callers don't need to know about the split.

Submodule layout:
- ``add``       — /add conversation, including the post-/add "Start learning" button payload
- ``quiz``      — /quiz conversation (revision)
- ``learn``     — /learn conversation (acquisition)
- ``simple``    — /start, /help, /list, /tags, /delete, /delete_confirm, /stats, error_handler
- ``reminders`` — /remindme, /reminders, /remindoff
- ``parsers``   — pure-function /add line parsers
- ``_shared``   — cross-flow helpers, callback-data prefixes, conversation state numbers
"""

# Re-export ConversationHandler so tests that do `from bot.handlers import ConversationHandler`
# still work — it's used as a state-end sentinel value in many test asserts.
from telegram.ext import ConversationHandler

# State numbers, callback-data prefixes, and shared helpers
from ._shared import (
    ADD_CONFIRM,
    ADD_WORDS,
    CB_ADD,
    CB_ART,
    CB_HELP,
    CB_LANG,
    CB_LEARN_ART,
    CB_LEARN_BATCH,
    CB_LEARN_MC,
    CB_LEARN_SHOW,
    CB_MC,
    CB_OWNER,
    CB_RATE,
    CONTACT_WRITING,
    LEARN_ANSWERING,
    PENDING_DELETE_TTL_S,
    PENDING_LEARN_TTL_S,
    QUIZ_ANSWERING,
    QUIZ_RATING,
    _drop_buttons,
    _format_word_tables,
    _get_lang,
    _parse_quiz_args,
    _safe_log,
    pending_pop,
    pending_set,
)

# /add
from .add import (
    ADD_FORMAT_MESSAGE,
    _save_words,
    add_callback,
    add_skip,
    add_start,
    add_words_received,
    get_add_conversation,
)

# /contact owner
from .contact import (
    contact_callback,
    contact_cancel,
    contact_command,
    contact_message,
    get_contact_conversation,
)

# /learn
from .learn import (
    get_learn_conversation,
    learn_batch_callback,
    learn_button_answer,
    learn_cancel,
    learn_start,
    learn_text_answer,
)

# /add line parsers (pure helpers)
from .parsers import (
    _parse_noun_line,
    _parse_simple_line,
    _parse_verb_line,
    _parse_word_line,
)

# /quiz
from .quiz import (
    _build_question_markup,
    _finish_quiz,
    _format_answer_response,
    _rating_keyboard,
    get_quiz_conversation,
    quiz_button_answer,
    quiz_cancel,
    quiz_rating,
    quiz_start,
    quiz_text_answer,
)

# /reminders
from .reminders import (
    _parse_remindme_args,
    reminders_command,
    remindme_command,
    remindoff_command,
)

# Simple commands + error handler
from .simple import (
    COMMANDS_HELP,
    START_MESSAGE,
    delete_command,
    delete_confirm_command,
    error_handler,
    help_callback,
    help_command,
    language_callback,
    language_command,
    list_command,
    start_command,
    stats_command,
    tags_command,
)

__all__ = [
    # ConversationHandler states + callback-data prefixes + constants
    "ADD_CONFIRM",
    "ADD_FORMAT_MESSAGE",
    "ADD_WORDS",
    "CB_ADD",
    "CB_ART",
    "CB_HELP",
    "CB_LEARN_ART",
    "CB_LEARN_BATCH",
    "CB_LEARN_MC",
    "CB_LEARN_SHOW",
    "CB_LANG",
    "CB_MC",
    "CB_OWNER",
    "CB_RATE",
    "COMMANDS_HELP",
    "CONTACT_WRITING",
    "ConversationHandler",
    "LEARN_ANSWERING",
    "PENDING_DELETE_TTL_S",
    "PENDING_LEARN_TTL_S",
    "QUIZ_ANSWERING",
    "QUIZ_RATING",
    "START_MESSAGE",
    # /contact owner
    "contact_callback",
    "contact_cancel",
    "contact_command",
    "contact_message",
    "get_contact_conversation",
    # /add
    "add_callback",
    "add_skip",
    "add_start",
    "add_words_received",
    "get_add_conversation",
    # /learn
    "get_learn_conversation",
    "learn_batch_callback",
    "learn_button_answer",
    "learn_cancel",
    "learn_start",
    "learn_text_answer",
    # /quiz
    "get_quiz_conversation",
    "quiz_button_answer",
    "quiz_cancel",
    "quiz_rating",
    "quiz_start",
    "quiz_text_answer",
    # Simple commands + error handler
    "delete_command",
    "delete_confirm_command",
    "error_handler",
    "help_callback",
    "help_command",
    "language_callback",
    "language_command",
    "list_command",
    "start_command",
    "stats_command",
    "tags_command",
    # /reminders
    "reminders_command",
    "remindme_command",
    "remindoff_command",
    # Helpers exposed for tests
    "_build_question_markup",
    "_drop_buttons",
    "_finish_quiz",
    "_format_answer_response",
    "_format_word_tables",
    "_get_lang",
    "_parse_noun_line",
    "_parse_quiz_args",
    "_parse_remindme_args",
    "_parse_simple_line",
    "_parse_verb_line",
    "_parse_word_line",
    "_rating_keyboard",
    "_safe_log",
    "_save_words",
    "pending_pop",
    "pending_set",
]
