from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.database import (
    add_reminder,
    add_word,
    delete_all_reminders,
    delete_reminder,
    get_all_reminders,
    get_reminders,
)
from bot.reminders import (
    DEFAULT_TZ,
    _reminder_callback,
    cancel_reminder,
    format_in_zones,
    job_name,
    load_all_reminders,
    schedule_reminder,
    validate_timezone,
)
from tests.helpers import graduate_word

USER_ID = 12345


class TestValidateTimezone:
    def test_valid_iana(self):
        assert validate_timezone("Europe/Berlin")
        assert validate_timezone("Europe/Moscow")
        assert validate_timezone("UTC")
        assert validate_timezone("Asia/Tokyo")

    def test_invalid(self):
        assert not validate_timezone("Not/AZone")
        assert not validate_timezone("BERLIN")
        assert not validate_timezone("")


class TestFormatInZones:
    def test_berlin_to_moscow(self):
        zones = format_in_zones(9, 0, "Europe/Berlin")
        assert zones["Europe/Berlin"] == "09:00"
        # Moscow is +1 to +2 hours ahead of Berlin (depending on DST). Always >= 10:00.
        assert zones["Europe/Moscow"] in ("10:00", "11:00")

    def test_utc_to_zones(self):
        zones = format_in_zones(12, 0, "UTC")
        # Berlin is UTC+1 or UTC+2; Moscow is UTC+3
        assert zones["Europe/Berlin"] in ("13:00", "14:00")
        assert zones["Europe/Moscow"] == "15:00"

    def test_returns_both_zones(self):
        zones = format_in_zones(0, 0, "Europe/Berlin")
        assert "Europe/Berlin" in zones
        assert "Europe/Moscow" in zones


class TestDatabaseReminders:
    async def test_add_and_get(self, db):
        rid = await add_reminder(db, USER_ID, 9, 0, "Europe/Berlin")
        items = await get_reminders(db, USER_ID)
        assert len(items) == 1
        assert items[0]["id"] == rid
        assert items[0]["hour"] == 9
        assert items[0]["minute"] == 0
        assert items[0]["timezone"] == "Europe/Berlin"

    async def test_default_tz(self, db):
        await add_reminder(db, USER_ID, 9, 0)
        items = await get_reminders(db, USER_ID)
        assert items[0]["timezone"] == "Europe/Berlin"

    async def test_invalid_hour(self, db):
        with pytest.raises(ValueError, match="hour"):
            await add_reminder(db, USER_ID, 24, 0, "UTC")

    async def test_invalid_minute(self, db):
        with pytest.raises(ValueError, match="minute"):
            await add_reminder(db, USER_ID, 9, 60, "UTC")

    async def test_multiple_per_user(self, db):
        await add_reminder(db, USER_ID, 9, 0, "Europe/Berlin")
        await add_reminder(db, USER_ID, 18, 30, "Europe/Berlin")
        items = await get_reminders(db, USER_ID)
        assert len(items) == 2

    async def test_get_reminders_user_isolation(self, db):
        await add_reminder(db, USER_ID, 9, 0)
        items = await get_reminders(db, 99999)
        assert items == []

    async def test_delete_one(self, db):
        rid = await add_reminder(db, USER_ID, 9, 0)
        await add_reminder(db, USER_ID, 18, 0)
        deleted = await delete_reminder(db, USER_ID, rid)
        assert deleted is True
        items = await get_reminders(db, USER_ID)
        assert len(items) == 1
        assert items[0]["id"] != rid

    async def test_delete_nonexistent(self, db):
        deleted = await delete_reminder(db, USER_ID, 9999)
        assert deleted is False

    async def test_delete_wrong_user(self, db):
        rid = await add_reminder(db, USER_ID, 9, 0)
        deleted = await delete_reminder(db, 99999, rid)
        assert deleted is False

    async def test_delete_all(self, db):
        await add_reminder(db, USER_ID, 9, 0)
        await add_reminder(db, USER_ID, 18, 0)
        count = await delete_all_reminders(db, USER_ID)
        assert count == 2
        assert await get_reminders(db, USER_ID) == []

    async def test_get_all_reminders(self, db):
        await add_reminder(db, USER_ID, 9, 0)
        await add_reminder(db, 99999, 18, 0)
        all_items = await get_all_reminders(db)
        assert len(all_items) == 2


class TestScheduleReminder:
    def test_schedules_with_correct_name(self):
        app = MagicMock()
        app.job_queue = MagicMock()
        reminder = {
            "id": 42,
            "user_id": USER_ID,
            "hour": 9,
            "minute": 0,
            "timezone": "Europe/Berlin",
        }
        schedule_reminder(app, reminder)
        app.job_queue.run_daily.assert_called_once()
        call = app.job_queue.run_daily.call_args
        assert call.kwargs["name"] == "reminder_42"
        assert call.kwargs["data"] == {"user_id": USER_ID}

    def test_no_jobqueue_logs_warning(self):
        app = MagicMock()
        app.job_queue = None
        reminder = {
            "id": 1,
            "user_id": USER_ID,
            "hour": 9,
            "minute": 0,
            "timezone": "UTC",
        }
        # Must not raise
        schedule_reminder(app, reminder)


class TestCancelReminder:
    def test_cancels_existing(self):
        app = MagicMock()
        app.job_queue = MagicMock()
        fake_job = MagicMock()
        app.job_queue.get_jobs_by_name.return_value = [fake_job]
        result = cancel_reminder(app, 42)
        assert result is True
        fake_job.schedule_removal.assert_called_once()

    def test_no_jobs_returns_false(self):
        app = MagicMock()
        app.job_queue = MagicMock()
        app.job_queue.get_jobs_by_name.return_value = []
        assert cancel_reminder(app, 42) is False

    def test_no_jobqueue(self):
        app = MagicMock()
        app.job_queue = None
        assert cancel_reminder(app, 42) is False


class TestLoadAllReminders:
    async def test_loads_and_schedules(self, db):
        await add_reminder(db, USER_ID, 9, 0, "Europe/Berlin")
        await add_reminder(db, USER_ID, 18, 30, "UTC")
        app = MagicMock()
        app.job_queue = MagicMock()
        count = await load_all_reminders(app, db)
        assert count == 2
        assert app.job_queue.run_daily.call_count == 2

    async def test_empty(self, db):
        app = MagicMock()
        app.job_queue = MagicMock()
        count = await load_all_reminders(app, db)
        assert count == 0


class TestReminderCallback:
    async def test_message_includes_learning_overview(self, db):
        word_id = await add_word(db, USER_ID, "adj", "schnell", "fast")
        await add_word(db, USER_ID, "adj", "neu", "new")
        await graduate_word(db, word_id, user_id=USER_ID)

        context = MagicMock()
        context.job.data = {"user_id": USER_ID}
        context.application.bot_data = {"db_conn": db}
        context.bot.send_message = AsyncMock()

        await _reminder_callback(context)

        call = context.bot.send_message.await_args
        assert call.kwargs["chat_id"] == USER_ID
        assert call.kwargs["parse_mode"] == "HTML"
        text = call.kwargs["text"]
        assert "Ready to review" in text
        assert "Waiting to learn" in text


class TestJobName:
    def test_format(self):
        assert job_name(42) == "reminder_42"


# --- Handler tests ---


class TestRemindmeCommand:
    async def test_valid_with_default_tz(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        fake_context.application = MagicMock()
        fake_context.application.job_queue = MagicMock()
        fake_context.args = ["09:00"]
        upd = fake_update()
        await remindme_command(upd, fake_context)
        items = await get_reminders(db, 12345)
        assert len(items) == 1
        assert items[0]["hour"] == 9 and items[0]["minute"] == 0
        assert items[0]["timezone"] == DEFAULT_TZ
        text = upd.message.reply_text.call_args.args[0]
        assert "Reminder #" in text
        assert "Berlin" in text and "Moscow" in text
        assert "Default timezone is Europe/Berlin" in text

    async def test_valid_with_custom_tz(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        fake_context.application = MagicMock()
        fake_context.application.job_queue = MagicMock()
        fake_context.args = ["18:30", "Europe/Moscow"]
        upd = fake_update()
        await remindme_command(upd, fake_context)
        items = await get_reminders(db, 12345)
        assert len(items) == 1
        assert items[0]["timezone"] == "Europe/Moscow"
        text = upd.message.reply_text.call_args.args[0]
        assert "Default timezone" not in text  # explicit tz given

    async def test_no_args(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        upd = fake_update()
        await remindme_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Usage" in text

    async def test_invalid_time(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        fake_context.args = ["abc"]
        upd = fake_update()
        await remindme_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "HH:MM" in text

    async def test_out_of_range_hour(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        fake_context.args = ["25:00"]
        upd = fake_update()
        await remindme_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "0-23" in text

    async def test_invalid_tz(self, fake_update, fake_context, db):
        from bot.handlers import remindme_command

        fake_context.args = ["09:00", "Not/AZone"]
        upd = fake_update()
        await remindme_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Unknown timezone" in text


class TestRemindersCommand:
    async def test_empty_list(self, fake_update, fake_context, db):
        from bot.handlers import reminders_command

        upd = fake_update()
        await reminders_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No reminders" in text

    async def test_lists_with_zones(self, fake_update, fake_context, db):
        from bot.handlers import reminders_command

        await add_reminder(db, 12345, 9, 0, "Europe/Berlin")
        upd = fake_update()
        await reminders_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "#" in text  # reminder ID
        assert "Berlin" in text and "Moscow" in text
        assert "/remindoff" in text


class TestRemindoffCommand:
    async def test_no_args(self, fake_update, fake_context, db):
        from bot.handlers import remindoff_command

        upd = fake_update()
        await remindoff_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "Usage" in text

    async def test_remove_specific(self, fake_update, fake_context, db):
        from bot.handlers import remindoff_command

        rid = await add_reminder(db, 12345, 9, 0)
        fake_context.application = MagicMock()
        fake_context.application.job_queue = MagicMock()
        fake_context.application.job_queue.get_jobs_by_name.return_value = []
        fake_context.args = [str(rid)]
        upd = fake_update()
        await remindoff_command(upd, fake_context)
        assert await get_reminders(db, 12345) == []
        text = upd.message.reply_text.call_args.args[0]
        assert f"Removed reminder #{rid}" in text

    async def test_remove_all(self, fake_update, fake_context, db):
        from bot.handlers import remindoff_command

        await add_reminder(db, 12345, 9, 0)
        await add_reminder(db, 12345, 18, 0)
        fake_context.application = MagicMock()
        fake_context.application.job_queue = MagicMock()
        fake_context.application.job_queue.get_jobs_by_name.return_value = []
        fake_context.args = ["all"]
        upd = fake_update()
        await remindoff_command(upd, fake_context)
        assert await get_reminders(db, 12345) == []
        text = upd.message.reply_text.call_args.args[0]
        assert "Removed 2" in text

    async def test_remove_nonexistent(self, fake_update, fake_context, db):
        from bot.handlers import remindoff_command

        fake_context.application = MagicMock()
        fake_context.application.job_queue = MagicMock()
        fake_context.application.job_queue.get_jobs_by_name.return_value = []
        fake_context.args = ["999"]
        upd = fake_update()
        await remindoff_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "No reminder" in text

    async def test_invalid_arg(self, fake_update, fake_context, db):
        from bot.handlers import remindoff_command

        fake_context.args = ["abc"]
        upd = fake_update()
        await remindoff_command(upd, fake_context)
        text = upd.message.reply_text.call_args.args[0]
        assert "must be a number" in text


class TestParseRemindmeArgs:
    def test_no_args(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args([])
        assert isinstance(result, str) and "Usage" in result

    def test_valid(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args(["09:00", "Europe/Berlin"])
        assert result == (9, 0, "Europe/Berlin")

    def test_default_tz(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args(["09:00"])
        assert result == (9, 0, "Europe/Berlin")

    def test_no_colon(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args(["0900"])
        assert isinstance(result, str) and "HH:MM" in result

    def test_non_numeric_time(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args(["aa:bb"])
        assert isinstance(result, str)

    def test_out_of_range(self):
        from bot.handlers import _parse_remindme_args

        result = _parse_remindme_args(["25:00"])
        assert isinstance(result, str) and "0-23" in result
