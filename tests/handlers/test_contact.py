from bot.handlers import (
    CONTACT_WRITING,
    ConversationHandler,
    contact_callback,
    contact_command,
    contact_message,
)
from tests.conftest import FakeContext


class TestContactOwner:
    async def test_contact_command_shows_owner_info(self, fake_update, monkeypatch):
        monkeypatch.setenv("OWNER_TG_NICKNAME", "owner_name")
        context = FakeContext(bot_data={})
        upd = fake_update()

        result = await contact_command(upd, context)

        assert result == ConversationHandler.END
        text = upd.message.reply_text.call_args.args[0]
        assert "@owner_name" in text
        assert "anonymously" in text
        markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == "owner:write"

    async def test_contact_info_callback_from_help(self, fake_update, monkeypatch):
        monkeypatch.setenv("OWNER_TG_NICKNAME", "@owner_name")
        context = FakeContext(bot_data={})
        upd = fake_update(callback_data="owner:info")

        result = await contact_callback(upd, context)

        assert result == ConversationHandler.END
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "@owner_name" in text

    async def test_write_callback_starts_letter_flow(self, fake_update):
        context = FakeContext(bot_data={})
        upd = fake_update(callback_data="owner:write")

        result = await contact_callback(upd, context)

        assert result == CONTACT_WRITING
        text = upd.callback_query.edit_message_text.call_args.args[0]
        assert "next message" in text

    async def test_message_forwarded_without_sender_info(self, fake_update, monkeypatch):
        monkeypatch.setenv("OWNER_USER_ID", "777")
        context = FakeContext(bot_data={})
        upd = fake_update(user_id=12345, text="I like the bot")

        result = await contact_message(upd, context)

        assert result == ConversationHandler.END
        kwargs = context.bot.send_message.call_args.kwargs
        assert kwargs["chat_id"] == 777
        assert "I like the bot" in kwargs["text"]
        assert "12345" not in kwargs["text"]
        assert "sender" not in kwargs["text"].lower()
        assert "sent anonymously" in upd.message.reply_text.call_args.args[0]

    async def test_missing_owner_id_explains_direct_contact(self, fake_update, monkeypatch):
        monkeypatch.delenv("OWNER_USER_ID", raising=False)
        monkeypatch.setenv("OWNER_TG_NICKNAME", "owner_name")
        context = FakeContext(bot_data={})
        upd = fake_update(text="hello")

        result = await contact_message(upd, context)

        assert result == ConversationHandler.END
        context.bot.send_message.assert_not_called()
        text = upd.message.reply_text.call_args.args[0]
        assert "not configured" in text
        assert "@owner_name" in text
