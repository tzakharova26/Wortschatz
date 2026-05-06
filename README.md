# Wortschatz

A Telegram bot for learning German vocabulary using spaced repetition (SM-2 algorithm).

## Features

- **Word cards** — nouns (article + plural), regular & irregular verbs (Partizip II + present forms), adjectives, adverbs, prepositions
- **Batch input** — add multiple words at once; space- or pipe-separated fields
- **Preview & confirm** — review parsed entries before saving; merges new tags into existing words instead of duplicating
- **Tags** — multiple per word; filter quizzes and listings by tag
- **4 quiz types** mixed in one session:
  - Translation to German (type the answer)
  - German to Translation (multiple choice)
  - Article quiz (der/die/das) for nouns
  - Verb forms quiz for irregular verbs
- **Configurable quiz size** — `/quiz N` runs N questions; words repeat with new quiz types when vocabulary is small
- **SM-2 spaced repetition** — words you struggle with appear more often; progress tracked per (word, quiz type) pair
- **Self-rating after each answer** — Anki-style 4-button quality scale plus a Misspell button that re-asks the word later
- **Daily reminders** — one or more per user, with timezone support (default Europe/Berlin); list shows Berlin and Moscow times
- **Statistics** — quizzes completed, words added, words learned (today/week/month/overall)
- **Umlaut tolerance** — type `ae`, `oe`, `ue`, `ss` or the proper Unicode forms; the bot accepts the simplified form but flags wrongly-added umlauts

## Quick Start

```bash
git clone <repo-url>
cd Wortschatz
cp .env.example .env
# Edit .env and set BOT_TOKEN=...

# Run locally
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m bot.main

# Or run with Docker (persistent volume keeps DB and logs)
docker compose up -d --build
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + commands + rating-button explanation |
| `/help` | Interactive help (Commands / How to add words / How quizzes work) |
| `/add [tag]` | Interactive batch add; tag is optional |
| `/list <tag>` | List words filtered by tag (max 40 per response) |
| `/tags` | Show all your tags |
| `/delete <word>` | Delete by German text (umlaut-aware); confirms with `/delete_confirm` if multiple matches |
| `/quiz [N] [tag]` | Start a quiz (default 7 questions); both args optional and order-independent |
| `/stats` | Learning statistics (today / week / month / overall) |
| `/remindme HH:MM [tz]` | Add a daily practice reminder (default `Europe/Berlin`) |
| `/reminders` | List your reminders with Berlin and Moscow times |
| `/remindoff <id\|all>` | Remove a specific reminder or all of them |
| `/cancel` | Cancel any in-progress conversation |

## Word Input Format

Each line is one word. Fields are separated by **spaces** or **`|` (pipe)** — pipe is auto-detected per line.

```
n <article> <word> <plural> <translation>
v <infinitive> <partizip_ii> <translation>                       (regular)
vi <infinitive> <partizip_ii> <ich> <du> <er> <translation>      (irregular)
adj <word> <translation>
adv <word> <translation>
prep <word> <translation>          (case info goes in translation)
```

Examples:

```
n die Katze Katzen cat
n | der Hund | Hunde | a friendly dog                  (pipe form)
v machen hat gemacht to do
vi fahren ist gefahren fahre faehrst faehrt to drive
adj schnell fast
adv manchmal sometimes
prep mit with (+dat)
```

## Roadmap

- [x] Core bot (word management, quizzes, SM-2, stats)
- [x] Daily reminders with timezone support
- [x] Configurable quiz size and word repetition
- [x] Preposition support
- [ ] AI-powered features (context sentences, grammar tips, smart corrections)

## Tech Stack

- Python 3.11+ / python-telegram-bot v21+ (with `[job-queue]` extra)
- SQLite (aiosqlite)
- APScheduler (transitively, for the JobQueue)
- Docker for deployment
