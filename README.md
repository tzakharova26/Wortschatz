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
- Provides a read-only SQLite web UI for inspecting the database.

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

`/stats` starts with the current learning queue:

- words ready to review,
- words waiting to learn,
- words already in review rotation.

Then it shows today, week, month, and overall counts for completed quizzes, added words, and learned words. `/learn` sessions are not counted as completed quizzes.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command overview |
| `/help` | Interactive help |
| `/add [tag]` | Add a batch of word cards |
| `/learn [N] [tag]` | Learn new or Blackout words |
| `/quiz [N] [tag]` | Review due words |
| `/stats` | Show learning statistics |
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
- `/learn` capped at 20 words
- `/quiz` capped at 50 questions
- misspell repeats capped at twice the initial quiz length
- database size warning at 100 MB, hard write stop at 500 MB
- anonymous owner letters capped at 2000 characters

## Tech Stack

- Python 3.11+
- python-telegram-bot, async handlers and JobQueue
- SQLite with aiosqlite
- SM-2 spaced repetition implemented in the app
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
  reminders.py         reminder scheduling
  handlers/contact.py  owner contact and anonymous letter flow
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

Stop the browser when done:

```bash
docker compose --profile tools stop db-browser
```

## Development

Run checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest tests/ -v
```

The test suite uses in-memory SQLite fixtures for most database coverage. Docker deployment keeps `.env` out of the image and persists runtime data through the `bot-data` volume.

## Roadmap

- AI-assisted context sentences
- Grammar hints for cards
- Smarter typo correction explanations
- Richer progress visualizations
