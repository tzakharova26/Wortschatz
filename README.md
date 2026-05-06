# Wortschatz

A Telegram bot for learning German vocabulary using spaced repetition (SM-2 algorithm).

## Features

- **Word cards** — add nouns (with articles & plural), verbs (with irregular forms), adjectives, and adverbs
- **Batch input** — add multiple words at once in a compact format
- **Tags** — organize words by topic
- **4 quiz types** mixed in one session:
  - Translation to German (type the answer)
  - German to Translation (multiple choice)
  - Article quiz (der/die/das) for nouns
  - Verb forms quiz for irregular verbs
- **SM-2 spaced repetition** — words you struggle with appear more often
- **Statistics** — track quizzes completed, words added, and words learned (daily/weekly/monthly)
- **Umlaut support** — type `ae`, `oe`, `ue` or `a`, `o`, `u` — both accepted

## Quick Start

```bash
# Clone and configure
git clone <repo-url>
cd Wortschatz
cp .env.example .env
# Edit .env and set your BOT_TOKEN

# Run locally
pip install -r requirements.txt
python -m bot.main

# Or run with Docker
docker-compose up -d
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with tutorial |
| `/help` | List all commands with format examples |
| `/add` | Add word cards (interactive, batch) |
| `/list` | List all words |
| `/list #tag` | List words by tag |
| `/tags` | Show all tags |
| `/delete <word>` | Delete a word |
| `/quiz` | Start a 7-question quiz (SM-2 picks words) |
| `/quiz #tag` | Quiz within a specific tag |
| `/stats` | Learning statistics |

## Word Input Format

```
n <article> <word> <plural> <translation>
v <infinitive> <partizip_ii> <translation>
v <infinitive> <partizip_ii> <ich> <du> <er> <translation>
adj <word> <translation>
adv <word> <translation>
```

Examples:
```
n die Katze Katzen cat
v machen hat gemacht to do
v fahren ist gefahren fahre faehrst faehrt to drive
adj schnell fast
adv manchmal sometimes
```

## Roadmap

- [x] Core bot (word management, quizzes, SM-2, stats)
- [ ] AI-powered features (context sentences, grammar tips, smart corrections)

## Tech Stack

- Python 3.11+ / python-telegram-bot v20+
- SQLite (aiosqlite)
- Docker for deployment
