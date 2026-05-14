import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import aiosqlite
from PIL import Image, ImageDraw, ImageFont

from bot.database import get_stats
from bot.i18n import normalize_language
from bot.reminders import DEFAULT_TZ

# Anchor "today / week / month" to the bot's default user timezone (Europe/Berlin).
# Without this, naive datetime.now() in Docker (which defaults to UTC) would make
# "Today" reset at the wrong hour for the user.
_STATS_TZ = ZoneInfo(DEFAULT_TZ)


@dataclass(frozen=True)
class ActivityPoint:
    label: str
    quizzes: int
    words_added: int
    words_learned: int

    @property
    def total(self) -> int:
        return self.quizzes + self.words_added + self.words_learned


async def get_user_stats(conn: aiosqlite.Connection, user_id: int, lang: str = "en") -> str:
    """Format user statistics for display."""
    lang = normalize_language(lang)
    now_local = datetime.now(_STATS_TZ)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    today_stats = await get_stats(conn, user_id, today)
    week_stats = await get_stats(conn, user_id, week_ago)

    def _fmt(s: dict) -> str:
        if lang == "ru":
            return (
                f"  Квизы: {s['quizzes_completed']}\n"
                f"  Добавлено слов: {s['words_added']}\n"
                f"  Выучено слов: {s['words_learned']}"
            )
        return (
            f"  Quizzes: {s['quizzes_completed']}\n"
            f"  Words added: {s['words_added']}\n"
            f"  Words learned: {s['words_learned']}"
        )

    if lang == "ru":
        return (
            "<b>Твоя статистика</b>\n\n"
            f"<b>Сегодня:</b>\n{_fmt(today_stats)}\n\n"
            f"<b>За 7 дней:</b>\n{_fmt(week_stats)}"
        )
    return (
        "<b>Your Statistics</b>\n\n"
        f"<b>Today:</b>\n{_fmt(today_stats)}\n\n"
        f"<b>This week:</b>\n{_fmt(week_stats)}"
    )


async def get_activity_points(
    conn: aiosqlite.Connection,
    user_id: int,
    starts: list[datetime],
    labels: list[str],
    final_end: datetime | None = None,
) -> list[ActivityPoint]:
    """Aggregate quiz/learn/add activity for consecutive local time buckets."""
    if len(starts) != len(labels):
        raise ValueError("starts and labels must have the same length")
    points: list[ActivityPoint] = []
    for idx, start in enumerate(starts):
        if idx + 1 < len(starts):
            end = starts[idx + 1]
        elif final_end is not None:
            end = final_end
        else:
            end = start + timedelta(days=1)
        start_str = _to_db_time(start)
        end_str = _to_db_time(end)
        quiz = await _count_quiz_activity(conn, user_id, start_str, end_str)
        words_added = await _count_words_added(conn, user_id, start_str, end_str)
        words_learned = await _count_words_learned(conn, user_id, start_str, end_str)
        points.append(
            ActivityPoint(
                label=labels[idx],
                quizzes=quiz["quizzes"],
                words_added=words_added,
                words_learned=words_learned,
            )
        )
    return points


async def build_stats_chart_svg(
    conn: aiosqlite.Connection,
    user_id: int,
    lang: str = "en",
    now: datetime | None = None,
) -> str:
    """Build an SVG fallback representation for tests/debugging."""
    data = await _build_activity_data(conn, user_id, lang, now)
    return _render_activity_svg(data["sections"], streak=data["streak"], lang=data["lang"])


async def build_stats_chart_file(
    conn: aiosqlite.Connection,
    user_id: int,
    lang: str = "en",
) -> BytesIO:
    data = await _build_activity_data(conn, user_id, lang)
    image = _render_activity_png(data["sections"], streak=data["streak"], lang=data["lang"])
    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "wortschatz_stats.png"
    return buf


async def _build_activity_data(
    conn: aiosqlite.Connection,
    user_id: int,
    lang: str = "en",
    now: datetime | None = None,
) -> dict:
    lang = normalize_language(lang)
    now_local = now.astimezone(_STATS_TZ) if now else datetime.now(_STATS_TZ)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    week_starts = [today - timedelta(days=6 - i) for i in range(7)]
    week_labels = [d.strftime("%a") for d in week_starts]

    month_starts = [today - timedelta(days=29 - i) for i in range(30)]
    month_labels = [
        d.strftime("%d") if i in {0, 6, 13, 20, 29} else "" for i, d in enumerate(month_starts)
    ]

    first_this_month = today.replace(day=1)
    year_starts = [_add_months(first_this_month, -11 + i) for i in range(12)]
    year_labels = [d.strftime("%b") for d in year_starts]

    week = await get_activity_points(
        conn, user_id, week_starts, week_labels, today + timedelta(days=1)
    )
    month = await get_activity_points(
        conn, user_id, month_starts, month_labels, today + timedelta(days=1)
    )
    year = await get_activity_points(
        conn, user_id, year_starts, year_labels, _add_months(first_this_month, 1)
    )
    return {
        "lang": lang,
        "streak": _review_streak(month),
        "sections": [("week", week), ("month", month), ("year", year)],
    }


def _to_db_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    return dt.replace(year=year, month=month, day=1)


async def _count_quiz_activity(
    conn: aiosqlite.Connection, user_id: int, start: str, end: str
) -> dict[str, int]:
    cursor = await conn.execute(
        """SELECT
             COUNT(*) AS quizzes
           FROM quiz_history
           WHERE user_id = ? AND source = 'quiz'
             AND answered_at >= ? AND answered_at < ?""",
        (user_id, start, end),
    )
    row = await cursor.fetchone()
    return {
        "quizzes": row["quizzes"] or 0,
    }


async def _count_words_added(conn: aiosqlite.Connection, user_id: int, start: str, end: str) -> int:
    cursor = await conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM words
           WHERE user_id = ? AND added_at >= ? AND added_at < ?""",
        (user_id, start, end),
    )
    row = await cursor.fetchone()
    return row["cnt"] or 0


async def _count_words_learned(
    conn: aiosqlite.Connection, user_id: int, start: str, end: str
) -> int:
    cursor = await conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM (
               SELECT h.word_id, MIN(h.answered_at) AS learned_at
               FROM quiz_history h
               JOIN words w ON w.id = h.word_id AND w.user_id = h.user_id
               WHERE h.user_id = ? AND h.source = 'learn'
                 AND NOT EXISTS (
                   SELECT 1 FROM sm2_state s
                   WHERE s.word_id = w.id
                     AND s.user_id = w.user_id
                     AND s.quiz_type = 'word'
                     AND s.last_quality = 0
                 )
               GROUP BY h.word_id
           ) learned
           WHERE learned_at >= ? AND learned_at < ?""",
        (user_id, start, end),
    )
    row = await cursor.fetchone()
    return row["cnt"] or 0


def _review_streak(points: list[ActivityPoint]) -> int:
    streak = 0
    for point in reversed(points):
        if point.quizzes <= 0:
            break
        streak += 1
    return streak


def _font(size: int, bold: bool = False):
    names = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_activity_png(
    sections: list[tuple[str, list[ActivityPoint]]],
    streak: int,
    lang: str,
) -> Image.Image:
    width = 1200
    section_h = 315
    height = 150 + section_h * len(sections)
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)

    title = "Статистика Wortschatz" if lang == "ru" else "Wortschatz Statistics"
    streak_label = (
        f"Серия повторений: {streak} дн." if lang == "ru" else f"Review streak: {streak} day(s)"
    )
    draw.text((48, 34), title, fill="#18202b", font=_font(36, bold=True))
    draw.text((48, 82), streak_label, fill="#667085", font=_font(22))
    _draw_legend(draw, 610, 56, lang)

    y = 130
    section_names = {
        "week": "7 дней" if lang == "ru" else "Last 7 days",
        "month": "30 дней" if lang == "ru" else "Last 30 days",
        "year": "12 месяцев" if lang == "ru" else "Last 12 months",
    }
    for key, points in sections:
        _draw_section(draw, 48, y, width - 96, section_h - 35, section_names[key], points, lang)
        y += section_h
    return image


def _draw_legend(draw: ImageDraw.ImageDraw, x: int, y: int, lang: str) -> None:
    labels = ("Квизы", "Выучено", "Добавлено") if lang == "ru" else ("Quizzes", "Learned", "Added")
    colors = ["#2563eb", "#16a34a", "#f59e0b"]
    cursor = x
    for color, label in zip(colors, labels, strict=True):
        draw.rounded_rectangle((cursor, y - 16, cursor + 18, y + 2), radius=4, fill=color)
        draw.text((cursor + 26, y - 18), label, fill="#344054", font=_font(18))
        cursor += 115


def _draw_section(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    points: list[ActivityPoint],
    lang: str,
) -> None:
    draw.text((x, y), title, fill="#18202b", font=_font(26, bold=True))

    total_quizzes = sum(p.quizzes for p in points)
    total_learned = sum(p.words_learned for p in points)
    total_added = sum(p.words_added for p in points)
    if lang == "ru":
        summary = f"Квизы {total_quizzes} | Выучено {total_learned} | Добавлено {total_added}"
    else:
        summary = f"Quizzes {total_quizzes} | Learned {total_learned} | Added {total_added}"
    draw.text((x + 305, y + 5), summary, fill="#344054", font=_font(18))

    chart_x = x + 10
    chart_y = y + 62
    chart_w = width - 20
    chart_h = height - 105
    axis_y = chart_y + chart_h
    draw.line((chart_x, axis_y, chart_x + chart_w, axis_y), fill="#d0d5dd", width=1)

    max_total = max([p.total for p in points] + [1])
    bar_gap = 5
    bar_w = max(6, (chart_w - bar_gap * (len(points) - 1)) / max(1, len(points)))
    for i, point in enumerate(points):
        bx = chart_x + i * (bar_w + bar_gap)
        current_y = axis_y
        for value, color in (
            (point.words_added, "#f59e0b"),
            (point.words_learned, "#16a34a"),
            (point.quizzes, "#2563eb"),
        ):
            if value <= 0:
                continue
            bar_h = max(3, chart_h * value / max_total)
            current_y -= bar_h
            draw.rounded_rectangle(
                (bx, current_y, bx + bar_w, current_y + bar_h),
                radius=3,
                fill=color,
            )
        if point.total > 0 and bar_w >= 18:
            label = str(point.total)
            bbox = draw.textbbox((0, 0), label, font=_font(14, bold=True))
            draw.text(
                (bx + (bar_w - (bbox[2] - bbox[0])) / 2, max(45, current_y - 20)),
                label,
                fill="#18202b",
                font=_font(14, bold=True),
            )
        if point.label:
            bbox = draw.textbbox((0, 0), point.label, font=_font(14))
            draw.text(
                (bx + (bar_w - (bbox[2] - bbox[0])) / 2, axis_y + 12),
                point.label,
                fill="#667085",
                font=_font(14),
            )


def _render_activity_svg(
    sections: list[tuple[str, list[ActivityPoint]]],
    streak: int,
    lang: str,
) -> str:
    width = 1100
    section_h = 260
    height = 130 + section_h * len(sections)
    title = "Статистика Wortschatz" if lang == "ru" else "Wortschatz Statistics"
    streak_label = (
        f"Серия повторений: {streak} дн." if lang == "ru" else f"Review streak: {streak} day(s)"
    )
    legend = ("Квизы", "Выучено", "Добавлено") if lang == "ru" else ("Quizzes", "Learned", "Added")
    section_names = {
        "week": "7 дней" if lang == "ru" else "Last 7 days",
        "month": "30 дней" if lang == "ru" else "Last 30 days",
        "year": "12 месяцев" if lang == "ru" else "Last 12 months",
    }

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<style>",
        "text{font-family:Arial,DejaVu Sans,sans-serif;fill:#18202b}",
        ".muted{fill:#667085;font-size:20px}.title{font-size:34px;font-weight:700}",
        ".section{font-size:25px;font-weight:700}.axis{stroke:#d0d5dd;stroke-width:1}",
        ".label{font-size:15px;fill:#667085}.small{font-size:17px;fill:#344054}",
        "</style>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="48" y="54" class="title">{html.escape(title)}</text>',
        f'<text x="48" y="88" class="muted">{html.escape(streak_label)}</text>',
        _legend_svg(610, 42, legend),
    ]

    y = 125
    for key, points in sections:
        parts.append(_section_svg(48, y, width - 96, section_h - 30, section_names[key], points))
        y += section_h
    parts.append("</svg>")
    return "\n".join(parts)


def _legend_svg(x: int, y: int, labels: tuple[str, str, str]) -> str:
    colors = ["#2563eb", "#16a34a", "#f59e0b"]
    items = []
    cursor = x
    for color, label in zip(colors, labels, strict=True):
        items.append(
            f'<rect x="{cursor}" y="{y - 14}" width="18" height="18" ' f'rx="4" fill="{color}"/>'
        )
        items.append(
            f'<text x="{cursor + 25}" y="{y + 1}" class="small">' f"{html.escape(label)}</text>"
        )
        cursor += 115
    return "\n".join(items)


def _section_svg(
    x: int, y: int, width: int, height: int, title: str, points: list[ActivityPoint]
) -> str:
    chart_x = x + 10
    chart_y = y + 52
    chart_w = width - 20
    chart_h = height - 86
    max_total = max([p.total for p in points] + [1])
    bar_gap = 4
    bar_w = max(5, (chart_w - bar_gap * (len(points) - 1)) / max(1, len(points)))
    parts = [
        f'<text x="{x}" y="{y + 24}" class="section">{html.escape(title)}</text>',
        f'<line x1="{chart_x}" y1="{chart_y + chart_h}" x2="{chart_x + chart_w}" '
        f'y2="{chart_y + chart_h}" class="axis"/>',
    ]
    for i, point in enumerate(points):
        bx = chart_x + i * (bar_w + bar_gap)
        current_y = chart_y + chart_h
        for value, color in (
            (point.words_added, "#f59e0b"),
            (point.words_learned, "#16a34a"),
            (point.quizzes, "#2563eb"),
        ):
            if value <= 0:
                continue
            h = max(2, chart_h * value / max_total)
            current_y -= h
            parts.append(
                f'<rect x="{bx:.1f}" y="{current_y:.1f}" width="{bar_w:.1f}" '
                f'height="{h:.1f}" fill="{color}" rx="3"/>'
            )
        if point.label:
            parts.append(
                f'<text x="{bx + bar_w / 2:.1f}" y="{chart_y + chart_h + 22}" '
                f'text-anchor="middle" class="label">{html.escape(point.label)}</text>'
            )
    return "\n".join(parts)
