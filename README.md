# Wortschatz

Wortschatz is a Telegram bot for learning German vocabulary with active recall and spaced repetition. It was built as a practical pet project: small enough to run on a VPS, but complete enough to use every day for adding words, drilling new vocabulary, reviewing due cards, and tracking progress.

The bot focuses on the parts of German that are easy to forget in a plain word list: noun articles and plurals, Partizip II, and irregular present-tense verb forms.

## What It Does

- Adds vocabulary cards from Telegram, one word or a batch at a time.
- Supports nouns, verbs, irregular verbs, adjectives, adverbs, and prepositions.
- Keeps German-specific fields: articles, plurals, Partizip II, and irregular forms.
- Separates first learning from long-term review:
  - `/learn` teaches new or forgotten words through a short drill.
  - `/quiz` reviews learned words when they are due by SM-2.
- Uses word-level SM-2 scheduling, while quiz type is chosen randomly for variety.
- Lets the user self-rate answers with Anki-style buttons: Good, Easy, Wrong, Blackout, or Misspell.
- Tracks daily, weekly, monthly, and overall statistics.
- Sends daily reminders with timezone support, a compact learning overview, and quick command buttons.
- Lets users contact the owner directly or send an anonymous letter through the bot.
- Supports English and Russian interface language per user.
- Provides a read-only SQLite web UI for inspecting the database.
- Provides owner-only `/health` checks and an optional Prometheus/Grafana monitoring profile.

## Interface Language

`/start` first shows a bilingual language choice with `English` and `Русский` buttons. After the user chooses, the bot saves the preference and shows the localized welcome text.

The language can be changed later with `/language`, `/language en`, or `/language ru`. The preference is stored per Telegram user in SQLite, so reminders and later sessions use the same language.

## Learning Flow

### Add Words

Words are added with `/add`. The bot parses the batch, shows a preview, and asks for confirmation before saving.

Examples:

```text
n die Katze Katzen cat
v machen hat gemacht to do
vi fahren ist gefahren fahre faehrst faehrt to drive
adj schnell fast
prep mit with (+dat)
```

Pipe-separated input is also supported and is easier when translations contain spaces:

```text
n | der Hund | Hunde | a friendly dog
vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive
```

Tags can be attached to batches and later used for filtered lists, learning, and quizzes.

### Learn New Words

`/learn` is a short massed-drill flow for words that are not yet in normal review. Each word starts with a card, then moves through recognition and production steps:

- See the full card.
- Choose the translation in multiple choice.
- Type the German word.
- For nouns: article and plural when available.
- For verbs: Partizip II, and irregular forms when available.

Correct answers advance silently, so the chat stays clean. Wrong answers are folded into the next prompt and retried later in the same session. A failed step can be retried twice, for three total attempts. A word graduates only when all required steps pass.
To keep Telegram readable, the bot edits the current step message for a short block of steps, then starts a fresh step message every 5 steps.

Blackout-rated words from `/quiz` return to `/learn`. In a normal learning session, Blackout words are tried before brand-new words, but they use at most half of the session.

### Review Due Words

`/quiz` reviews words that have graduated from `/learn` and are due according to SM-2. A session mixes several question types:

- Translate to German.
- Pick the translation from multiple choice.
- Choose `der`, `die`, or `das`.
- Type the plural.
- Type Partizip II.
- Type irregular verb forms such as `du` or `er/sie/es`.

After each answer, the bot shows a compact word card with the translation and relevant forms, then asks for a rating. The same bot message is edited into the next question, avoiding long runs of `Correct`, `Wrong`, and `Noted` messages.

### Track Progress

`/stats` sends a short text summary with only today and week counts for completed quizzes, added words, and learned words. `/learn` sessions are not counted as completed quizzes.

The command also sends an activity chart as an inline PNG picture with three views:

- last 7 days,
- last 30 days,
- last 12 months.

The chart shows quizzes, learned words, added words, and the current review streak.

### Monitor Health

`/health` is an owner-only command controlled by `OWNER_USER_ID`. It gives a compact Telegram status report:

- users and word counts against configured limits,
- learning queue, due review, and review rotation counts,
- active reminders,
- SQLite database size against warning/hard limits,
- warning/error log counts for today,
- last quiz and learn activity.

For deeper web monitoring, the optional Docker `monitoring` profile starts:

- a small read-only Prometheus exporter for aggregate bot metrics,
- Prometheus for time-series storage,
- Grafana for dashboards and ad-hoc charts.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Choose interface language, then show localized welcome |
| `/help` | Interactive help |
| `/add [tag]` | Add a batch of word cards |
| `/learn [N] [tag]` | Learn new or Blackout words |
| `/quiz [N] [tag]` | Review due words |
| `/stats` | Show today/week text stats and send a PNG activity chart |
| `/health` | Show owner-only bot health |
| `/language [en\|ru]` | Choose English or Russian interface |
| `/list <tag>` | List words by tag |
| `/tags` | Show all tags |
| `/delete <word>` | Delete a saved word |
| `/remindme HH:MM [tz]` | Add a daily reminder |
| `/reminders` | List reminders |
| `/remindoff <id\|all>` | Remove reminders |
| `/contact` | Show owner contact info or send an anonymous letter |
| `/cancel` | Cancel the current conversation |

## German Input Details

Supported card formats:

```text
n <article> <word> <plural> <translation>
v <infinitive> <partizip_ii> <translation>
vi <infinitive> <partizip_ii> <ich> <du> <er/sie/es> <translation>
adj <word> <translation>
adv <word> <translation>
prep <word> <translation>
```

The `vi` marker is used for irregular verbs so that multi-word translations do not conflict with verb forms.

Umlaut matching is directional:

- `ä`, `ö`, `ü`, `ß` can be typed as `ae`, `oe`, `ue`, `ss`.
- Adding a special character where the stored word has a plain letter is still wrong.

This lets the user type quickly on any keyboard without making the checker too permissive.

## Safety Limits

The bot is configured for a small personal deployment, so it has explicit bounds. If a command hits a bound, the bot explains what happened, logs a warning, and avoids partial writes.

Current limits:

- 10 users with persisted data
- 5000 words per user
- 50 lines per `/add` batch
- 8000 characters per `/add` message
- 120 characters per German field or translation
- 5 tags per word
- 100 tags per user
- 32 characters per tag
- 10 reminders per user
- `/learn` capped at 10 words
- `/quiz` capped at 50 questions
- misspell repeats capped at twice the initial quiz length
- database size warning at 100 MB, hard write stop at 500 MB
- anonymous owner letters capped at 2000 characters

## Tech Stack

- Python 3.11+
- python-telegram-bot, async handlers and JobQueue
- SQLite with aiosqlite
- SM-2 spaced repetition implemented in the app
- Pillow for generated stats chart images
- prometheus-client for the optional metrics exporter
- Docker Compose deployment
- pytest and pytest-asyncio
- ruff for linting and formatting

## Project Structure

```text
bot/
  main.py              app startup
  handlers/            Telegram command and conversation handlers
  database.py          SQLite schema, migrations, and queries
  learn.py             /learn session logic
  quiz.py              /quiz question generation and result application
  safety.py            safety limits and graceful rejection helpers
  sm2.py               spaced repetition algorithm
  questions.py         shared answer matching and MC option helpers
  i18n.py              English/Russian interface text and language helpers
  reminders.py         reminder scheduling
  handlers/contact.py  owner contact and anonymous letter flow
  health.py            owner-only health snapshot formatting
  monitoring_exporter.py optional Prometheus metrics exporter
  stats.py             stats formatting
  umlaut.py            umlaut-aware matching utilities
tests/
  handlers/            handler-level tests
  test_*.py            core module tests
docker-compose.yml     bot service and optional DB browser
```

## Run Locally

```bash
git clone <repo-url>
cd Wortschatz
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Set `BOT_TOKEN` in `.env`, then run:

Optional owner-contact settings:

```text
OWNER_TG_NICKNAME=tatiana_zakhar
OWNER_USER_ID=123456789
```

`OWNER_TG_NICKNAME` is shown to users for direct contact. `OWNER_USER_ID` is the Telegram chat id that receives anonymous letters.
`OWNER_USER_ID` also controls access to `/health`.

```bash
.venv/bin/python -m bot.main
```

## Run With Docker

```bash
docker compose up -d --build bot
```

The bot stores its SQLite database and logs in the persistent Docker volume mounted at `/app/data`.

## Inspect The Database

Start the optional read-only SQLite web UI:

```bash
docker compose --profile tools up -d --build db-browser
```

Open:

```text
http://127.0.0.1:8080
```

If the bot is on a VPS, open an SSH tunnel from your laptop:

```bash
ssh -L 8080:127.0.0.1:8080 <user>@<server>
```

Useful tables:

- `words` — vocabulary cards and tags
- `sm2_state` — word-level spaced repetition state
- `quiz_history` — quiz and learn history, separated by `source`
- `reminders` — daily reminder settings
- `user_settings` — per-user interface language, currently `en` or `ru`

Stop the browser when done:

```bash
docker compose --profile tools stop db-browser
```

## Web Monitoring

Start the optional monitoring stack:

```bash
docker compose --profile monitoring up -d --build metrics-exporter prometheus grafana
```

Local URLs:

```text
http://127.0.0.1:9108/metrics
http://127.0.0.1:9090
http://127.0.0.1:3001
```

On a VPS, keep these ports bound to `127.0.0.1` and use an SSH tunnel:

```bash
ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 <user>@<server>
```

Grafana uses `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, and `GRAFANA_HOST_PORT` from `.env`; if omitted, the credentials default to `admin`/`admin` and the host port defaults to `3001`. Change the password before using it beyond a private SSH tunnel.

The exporter exposes aggregate metrics only, not Telegram user ids.

## Development

Run checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest tests/ -v
```

The test suite uses in-memory SQLite fixtures for most database coverage. Docker deployment keeps `.env` out of the image and persists runtime data through the `bot-data` volume.

## Roadmap

- [x] English/Russian interface language with `/start` choice and `/language`
- [ ] AI-assisted context sentences
- [ ] Grammar hints for cards
- [ ] Smarter typo correction explanations
- [x] PNG activity chart attached to `/stats`
- [ ] Richer progress visualizations
