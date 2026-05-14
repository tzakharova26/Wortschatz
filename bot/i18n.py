from __future__ import annotations

import html
from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en": "English", "ru": "Русский"}


def normalize_language(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANGUAGE
    lang = lang.strip().lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def word_label(count: int, lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        n = abs(count)
        if n % 10 == 1 and n % 100 != 11:
            return "слово"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "слова"
        return "слов"
    return "word" if count == 1 else "words"


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    lang = normalize_language(lang)
    text = _STRINGS.get(lang, {}).get(key)
    if text is None:
        text = _STRINGS[DEFAULT_LANGUAGE].get(key, key)
    return text.format(**kwargs)


def commands_help(lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        return (
            "<b>Команды:</b>\n"
            "/add [тег] — добавить новые слова, можно сразу с тегом\n"
            "/list тег — показать слова с выбранным тегом\n"
            "/tags — показать все теги\n"
            "/delete слово — удалить слово по немецкому написанию\n"
            "/quiz [N] [тег] — начать повторение (по умолчанию 7 вопросов)\n"
            "/learn [N] [тег] — выучить новые слова или слова после Blackout\n"
            "/stats — показать статистику\n"
            "/health — базовое состояние бота (только владелец)\n"
            "/language — выбрать язык интерфейса\n"
            "/remindme HH:MM [tz] — добавить ежедневное напоминание\n"
            "/reminders — список напоминаний\n"
            "/remindoff &lt;id|all&gt; — удалить напоминание\n"
            "/contact — связаться с владельцем или отправить анонимное письмо\n"
            "/help — интерактивная помощь\n"
            "/cancel — отменить текущую сессию"
        )
    return (
        "<b>Commands:</b>\n"
        "/add [tag] — add new words (optionally with a tag)\n"
        "/list tag — list words filtered by tag\n"
        "/tags — show all your tags\n"
        "/delete word — delete a word by its German text\n"
        "/quiz [N] [tag] — start a quiz (N questions, default 7; words repeat if vocab is small)\n"
        "/learn [N] [tag] — learn new (or Blackout-flagged) words; graduates them into /quiz\n"
        "/stats — show learning statistics\n"
        "/health — show basic bot health (owner only)\n"
        "/language — choose interface language\n"
        "/remindme HH:MM [tz] — add a daily practice reminder (default Europe/Berlin)\n"
        "/reminders — list your reminders (Berlin/Moscow times)\n"
        "/remindoff &lt;id|all&gt; — remove a reminder\n"
        "/contact — contact the owner or send an anonymous letter\n"
        "/help — interactive help menu\n"
        "/cancel — abort an active quiz (partial progress is saved)"
    )


def quiz_start_message(lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        return (
            "Время повторения. После каждого ответа оцени, насколько хорошо ты знала слово:\n\n"
            "  Хорошо — правильно, обычное усилие\n"
            "  Легко — правильно и легко\n"
            "  Опечатка — знала слово, но ошиблась в написании; вопрос вернется в конец\n"
            "  Ошиблась — вспомнила частично, но ответ неверный\n"
            "  Не вспомнила — совсем не вспомнила; слово вернется в /learn"
        )
    return (
        "Quiz time! After each answer, rate how well you knew it:\n\n"
        "  Good — correct, normal effort\n"
        "  Easy — correct and effortless\n"
        "  Misspell — you knew it but mistyped; the question returns at the end\n"
        "  Wrong — partially remembered, but answered wrong\n"
        "  Blackout — no idea; the word returns to /learn"
    )


def learn_start_message(n: int, lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        return (
            f"Учимся: {n} слов. Каждое слово проходит шаги:\n"
            "  1. Карточка  2. Выбор ответа  3. Ввод немецкого\n"
            "  + артикль и множественное число для существительных, "
            "Partizip II и формы для глаголов.\n"
            "Ошибочные шаги получат до двух повторов. Слово считается выученным "
            "только после правильного прохождения всех шагов."
        )
    return (
        f"Learning {n} word(s). Each word steps through:\n"
        "  1. See the card  2. Multiple choice  3. Type it\n"
        "  + article and plural (nouns), Partizip II and verb forms (verbs).\n"
        "Wrong steps get up to two retries. A word graduates only after every "
        "required step is correct."
    )


def start_message(lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        return (
            "Привет! Это Wortschatz — бот для немецкой лексики.\n\n"
            + commands_help(lang)
            + "\n\n"
            + quiz_start_message(lang)
        )
    return (
        "Welcome to Wortschatz — your German vocabulary trainer!\n\n"
        + commands_help(lang)
        + "\n\n"
        + quiz_start_message(lang)
    )


def add_format_message(lang: str = DEFAULT_LANGUAGE) -> str:
    lang = normalize_language(lang)
    if lang == "ru":
        return (
            "Отправь слова, по одному на строку. Поля можно разделять пробелами или |.\n\n"
            "<code>n article word plural translation</code>\n"
            "Пример: <code>n die Katze Katzen cat</code>\n"
            "Или:    <code>n | die | Katze | Katzen | small cat</code>\n\n"
            "<code>v infinitive partizip_ii translation</code>  (правильный глагол)\n"
            "Пример: <code>v machen hat gemacht to do</code>\n"
            "Или:    <code>v | machen | hat gemacht | to do something</code>\n\n"
            "<code>vi infinitive partizip_ii ich du er translation</code>  (неправильный)\n"
            "Пример: <code>vi fahren ist gefahren fahre faehrst faehrt to drive</code>\n\n"
            "<code>adj word translation</code>\n"
            "Пример: <code>adj schnell fast</code>\n\n"
            "<code>adv word translation</code>\n"
            "Пример: <code>adv manchmal sometimes</code>\n\n"
            "<code>prep word translation</code>  (падеж можно писать в переводе)\n"
            "Пример: <code>prep mit with (+dat)</code>\n\n"
            "Лимиты: до 50 строк за раз, 120 символов для слова/перевода, "
            "5 тегов на слово, 32 символа на тег.\n\n"
            "После разбора ты увидишь предпросмотр с кнопками сохранения и отмены."
        )
    return (
        "Send words, one per line. Fields can be separated by spaces or by | (pipe).\n\n"
        "<code>n article word plural translation</code>\n"
        "Example: <code>n die Katze Katzen cat</code>\n"
        "Or:      <code>n | die | Katze | Katzen | small cat</code>\n\n"
        "<code>v infinitive partizip_ii translation</code>  (regular)\n"
        "Example: <code>v machen hat gemacht to do</code>\n"
        "Or:      <code>v | machen | hat gemacht | to do something</code>\n\n"
        "<code>vi infinitive partizip_ii ich du er translation</code>  (irregular)\n"
        "Example: <code>vi fahren ist gefahren fahre faehrst faehrt to drive</code>\n"
        "Or:      <code>vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive</code>\n\n"
        "<code>adj word translation</code>\n"
        "Example: <code>adj schnell fast</code>\n\n"
        "<code>adv word translation</code>\n"
        "Example: <code>adv manchmal sometimes</code>\n\n"
        "<code>prep word translation</code>  (case info goes in translation)\n"
        "Example: <code>prep mit with (+dat)</code>\n\n"
        "Limits: up to 50 lines per batch, 120 characters per word/translation, "
        "5 tags per word, 32 characters per tag.\n\n"
        "After parsing, you'll see a preview with Confirm and Cancel buttons."
    )


def safe(value: Any) -> str:
    return html.escape(str(value))


_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "language_prompt": "Choose interface language:",
        "language_set": "Interface language set to English.",
        "language_invalid": "Unknown language. Choose English or Russian.",
        "help_prompt": "What do you need help with?",
        "btn_commands": "Commands",
        "btn_add": "How to add words",
        "btn_practice": "Learn & quiz",
        "btn_contact": "Contact owner",
        "btn_language": "Language",
        "unknown_topic": "Unknown topic.",
        "error_generic": "Something went wrong, please try again later.",
        "no_tags": "You have no tags yet.",
        "your_tags": "Your tags:",
        "list_need_tag": "Please specify a tag: /list tag\nUse /tags to see your tags.",
        "list_empty": "No words found with tag #{tag}.",
        "list_header": "Words with tag <b>#{tag}</b> ({total} total):",
        "list_more": "... and {count} more.",
        "delete_usage": "Usage: /delete german_word",
        "delete_not_found": "No word '{word}' found in your vocabulary.",
        "delete_multi": "Multiple matches for '{word}':",
        "delete_confirm": "Delete all of them? Use /delete_confirm to confirm.",
        "delete_done": "Deleted: {word} — {translation}",
        "delete_failed": "Failed to delete word.",
        "delete_nothing": (
            "Nothing to confirm — your /delete request may have expired. Re-run /delete."
        ),
        "delete_count": "Deleted {count} word(s).",
        "practice_help": (
            "<b>Practice flow: /learn → /quiz</b>\n\n"
            "Brand-new words go through <b>/learn</b> first, then graduate into "
            "<b>/quiz</b> for spaced repetition.\n\n"
            "<b>/learn [N] [tag]</b> — acquisition. It shows a card, asks multiple choice, "
            "typed German, and extra forms when useful.\n\n"
            "<b>/quiz [N] [tag]</b> — revision. It mixes Translate, Multiple choice, "
            "Article, Plural, Partizip II, and verb forms when they apply.\n\n"
        ),
    },
    "ru": {
        "language_prompt": "Выбери язык интерфейса:",
        "language_set": "Язык интерфейса переключен на русский.",
        "language_invalid": "Неизвестный язык. Выбери English или Russian.",
        "help_prompt": "С чем помочь?",
        "btn_commands": "Команды",
        "btn_add": "Как добавлять",
        "btn_practice": "Учить и повторять",
        "btn_contact": "Написать владельцу",
        "btn_language": "Язык",
        "unknown_topic": "Неизвестный раздел.",
        "error_generic": "Что-то пошло не так, попробуй позже.",
        "no_tags": "У тебя пока нет тегов.",
        "your_tags": "Твои теги:",
        "list_need_tag": "Укажи тег: /list tag\nКоманда /tags покажет все теги.",
        "list_empty": "С тегом #{tag} слов не найдено.",
        "list_header": "Слова с тегом <b>#{tag}</b> (всего {total}):",
        "list_more": "... и еще {count}.",
        "delete_usage": "Формат: /delete german_word",
        "delete_not_found": "Слово '{word}' не найдено в твоем словаре.",
        "delete_multi": "Найдено несколько совпадений для '{word}':",
        "delete_confirm": "Удалить все? Подтверди командой /delete_confirm.",
        "delete_done": "Удалено: {word} — {translation}",
        "delete_failed": "Не удалось удалить слово.",
        "delete_nothing": (
            "Нечего подтверждать — запрос /delete мог устареть. Запусти /delete снова."
        ),
        "delete_count": "Удалено слов: {count}.",
        "practice_help": (
            "<b>Как работает практика: /learn → /quiz</b>\n\n"
            "Новые слова сначала проходят <b>/learn</b>, потом попадают в "
            "<b>/quiz</b> для интервального повторения.\n\n"
            "<b>/learn [N] [тег]</b> — первичное запоминание: карточка, выбор ответа, "
            "ввод немецкого и дополнительные формы, если они есть.\n\n"
            "<b>/quiz [N] [тег]</b> — повторение: перевод, выбор ответа, артикли, "
            "множественное число, Partizip II и формы глаголов.\n\n"
        ),
    },
}
