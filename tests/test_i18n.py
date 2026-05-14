from bot.i18n import (
    add_format_message,
    commands_help,
    learn_start_message,
    normalize_language,
    quiz_start_message,
    start_message,
    word_label,
)
from bot.learn import build_session
from bot.quiz import build_quiz_session, format_summary


def _word(**overrides):
    base = {
        "id": 1,
        "user_id": 12345,
        "part_of_speech": "n",
        "german": "Katze",
        "article": "die",
        "plural": "Katzen",
        "partizip_ii": None,
        "irregular_forms": None,
        "translation": "кошка",
        "tags": "",
    }
    base.update(overrides)
    return base


class TestI18n:
    def test_normalize_language(self):
        assert normalize_language("ru") == "ru"
        assert normalize_language("EN") == "en"
        assert normalize_language("de") == "en"
        assert normalize_language(None) == "en"

    def test_russian_static_messages(self):
        assert "Команды" in commands_help("ru")
        assert "/language" in commands_help("ru")
        assert "Привет" in start_message("ru")
        assert "Время повторения" in quiz_start_message("ru")
        assert "Учимся: 3" in learn_start_message(3, "ru")
        assert "Отправь слова" in add_format_message("ru")

    def test_russian_word_labels(self):
        assert word_label(1, "ru") == "слово"
        assert word_label(2, "ru") == "слова"
        assert word_label(5, "ru") == "слов"

    def test_quiz_prompts_and_summary_can_be_russian(self):
        word = _word()
        session = build_quiz_session(
            12345,
            [word],
            [word],
            size=1,
            lang="ru",
            temperature=1.0,
        )
        assert session.lang == "ru"
        assert any(
            phrase in session.questions[0].prompt
            for phrase in ("Переведи", "Что значит", "Какой артикль", "множественное")
        )

        session.record_result(4, True)
        assert "Повторение закончено" in format_summary(session)

    def test_learn_prompts_can_be_russian(self):
        word = _word()
        session = build_session(12345, [word], [word], lang="ru")
        assert session.lang == "ru"
        prompts = "\n".join(step.prompt for step in session.steps)
        assert "Что значит" in prompts
        assert "Напиши по-немецки" in prompts
