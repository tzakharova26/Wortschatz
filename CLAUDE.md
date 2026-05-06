# Wortschatz - German Vocabulary Telegram Bot

## Project Overview
A Telegram bot for learning German vocabulary using spaced repetition (SM-2 algorithm). Users add word cards, practice via mixed quizzes, and track progress.

## Tech Stack
- **Language:** Python 3.11+
- **Telegram library:** python-telegram-bot (v20+, async)
- **Database:** SQLite via aiosqlite (async)
- **Config:** python-dotenv, `.env` file for secrets
- **Deployment:** Docker on VPS
- **Venv:** always use `.venv` in project root

## Project Structure
```
Wortschatz/
  bot/
    __init__.py
    main.py            # Entry point, application setup
    handlers.py        # Telegram command & message handlers
    database.py        # Database models and queries
    quiz.py            # Quiz logic, question generation
    sm2.py             # SM-2 spaced repetition algorithm
    umlaut.py          # Umlaut conversion utilities
    logging_config.py  # Centralized logging setup
  tests/
    __init__.py
    conftest.py        # Shared fixtures (in-memory DB, etc.)
    test_database.py
    test_sm2.py
    test_quiz.py
    test_umlaut.py
    test_handlers.py
    test_logging_config.py
  .env                 # BOT_TOKEN (not committed)
  .env.example         # Template for .env
  .gitignore
  requirements.txt
  pyproject.toml       # ruff + pytest config
  Dockerfile
  docker-compose.yml
  CLAUDE.md
  README.md
```

## User Interface
- All bot messages are in **English**
- Word cards can be in any language pair (German + user's choice)
- Russian and other UTF-8 translations are fully supported

## Word Card Model

### Parts of Speech & Input Format

Interactive `/add` flow:
1. User sends `/add`
2. Bot replies with format instructions
3. User sends words, one per line
4. Bot asks for a tag (optional, one tag per batch)
5. Bot confirms added words

**Nouns (n):**
```
n <article> <word> <plural> <translation>
```
Example: `n die Katze Katzen cat`

**Verbs -- regular (v):**
```
v <infinitive> <partizip_ii> <translation>
```
Example: `v machen hat gemacht to do`

**Verbs -- irregular present (v):**
```
v <infinitive> <partizip_ii> <ich> <du> <er/sie/es> <translation>
```
Example: `v fahren ist gefahren fahre faehrst faehrt to drive`

**Adjectives (adj):**
```
adj <word> <translation>
```
Example: `adj schnell fast`

**Adverbs (adv):**
```
adv <word> <translation>
```
Example: `adv manchmal sometimes`

### Input Validation
- `part_of_speech` must be one of: `n`, `v`, `adj`, `adv`
- `german` and `translation` cannot be empty or whitespace-only
- All inputs are stripped of leading/trailing whitespace
- Tags are normalized: whitespace stripped, empty segments removed
- `quiz_type` must be one of: `translate`, `multiple_choice`, `article`, `verb_forms`

### Umlaut Handling
- Store and display proper Unicode (ae->a, oe->o, ue->u, ss->ss)
- Accept both ASCII and Unicode forms on input
- Accept both forms in quiz answers (e.g., "faehrt" and "fahrt" both accepted)

### Tags
- A word can have **multiple tags** (assigned across different `/add` sessions)
- Tags are optional, one tag per `/add` batch
- Stored as comma-separated string in `words.tags` column
- No default tag for untagged words

## Quiz System

### Quiz Types (mixed in one session)
1. **Translation -> German** -- bot shows translation, user types the German word (all parts of speech)
2. **Multiple choice German -> Translation** -- bot shows German word + 4 options; wrong options from same part of speech, preferring same tag, falling back to any words of same part of speech
3. **Article quiz** -- nouns only: bot shows noun, user picks der/die/das
4. **Verb forms quiz** -- irregular verbs only: bot shows infinitive, user types the irregular present form(s)

### Multiple Choice Fallback
When fewer than 4 words exist in the same tag + part of speech, fall back to same part of speech across all user's words.

### Session
- **7 questions** per session, mixed quiz types (only applicable types per word)
- `/quiz` -- SM-2 picks the 7 most due words across all vocabulary
- `/quiz #tag` -- picks the 7 most due (least reviewed) words within that tag

### SM-2 Spaced Repetition Algorithm
Full SM-2 implementation:
- Each word+quiz_type pair has its own SM-2 state (easiness factor, interval, repetitions)
- After each answer, update the SM-2 parameters
- Words with earliest due date are prioritized for quiz selection

### "Learned" Definition (for stats only)
A word is considered **learned** when all applicable quiz types have been passed at least **4 times total**:
- Noun: quizzes 1, 2, 3 (translation, multiple choice, article)
- Regular verb: quizzes 1, 2 (translation, multiple choice)
- Irregular verb: quizzes 1, 2, 4 (translation, multiple choice, verb forms)
- Adjective/Adverb: quizzes 1, 2 (translation, multiple choice)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with brief tutorial |
| `/help` | List all commands with format examples |
| `/add` | Interactive: add word cards (batch, one per line) |
| `/list` | List all words |
| `/list #tag` | List words filtered by tag |
| `/tags` | List all existing tags |
| `/delete <word>` | Delete a word card |
| `/quiz` | Start a 7-question mixed quiz (SM-2 selection) |
| `/quiz #tag` | Start a quiz within a specific tag |
| `/stats` | Show learning statistics |

## Statistics (`/stats`)
- **Today / This week / This month:**
  - Quizzes completed
  - Words added
  - Words learned (reached "learned" threshold)
- Overall totals

## Database Schema (SQLite)

```sql
CREATE TABLE words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    part_of_speech TEXT NOT NULL,  -- 'n', 'v', 'adj', 'adv'
    german TEXT NOT NULL,
    article TEXT,                   -- der/die/das (nouns only)
    plural TEXT,                    -- nouns only
    partizip_ii TEXT,               -- verbs only
    ich_form TEXT,                  -- irregular verbs only
    du_form TEXT,                   -- irregular verbs only
    er_form TEXT,                   -- irregular verbs only
    translation TEXT NOT NULL,
    tags TEXT DEFAULT '',           -- comma-separated, e.g. 'animals,A1'
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_words_user_id ON words(user_id);
CREATE INDEX idx_words_user_pos ON words(user_id, part_of_speech);

CREATE TABLE sm2_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    quiz_type TEXT NOT NULL,        -- 'translate', 'multiple_choice', 'article', 'verb_forms'
    easiness_factor REAL DEFAULT 2.5,
    interval INTEGER DEFAULT 0,
    repetitions INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    next_review TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(user_id, word_id, quiz_type)
);

CREATE INDEX idx_sm2_word_id ON sm2_state(word_id);
CREATE INDEX idx_sm2_user_next ON sm2_state(user_id, next_review);

CREATE TABLE quiz_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    quiz_type TEXT NOT NULL,
    correct INTEGER NOT NULL,       -- 0 or 1
    answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE INDEX idx_history_user_date ON quiz_history(user_id, answered_at);
```

## Development
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # add BOT_TOKEN
.venv/bin/python -m bot.main
```

## Docker
```bash
docker-compose up -d
```

The `data/` directory is mounted as a persistent Docker volume (`bot-data:/app/data`), so the database and log files survive container restarts.

## Logging & Error Handling
- **Log file:** `data/bot.log` (persisted via Docker volume)
- **Rotation:** `RotatingFileHandler`, 5 MB max, 3 backups, UTF-8 encoding
- **Format:** `[%(asctime)s] %(levelname)s %(name)s (user=%(user_id)s): %(message)s`
- **Levels:**
  - `INFO` -- every incoming command (user_id, command, args), successful mutations
  - `WARNING` -- malformed input, non-existent resources, empty tags, suspicious patterns
  - `ERROR` -- crashes, DB connection failures, Telegram API failures (logged once at handler level with full traceback)
- **Error handling:** never fail silently. On any unhandled error, send a user-facing message: "Something went wrong, please try again later." and log the full traceback
- **Architecture:** data layer logs INFO (actions) and WARNING (business logic). ERROR logging happens once at the handler/error-handler level to avoid duplicate logs.
- **Module:** `bot/logging_config.py`

## Testing & Linting
- **Tests:** pytest + pytest-asyncio
- **Linter:** ruff (lint + format)
- Run tests: `.venv/bin/pytest tests/ -v`
- Run linter: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- Every module gets a corresponding test file
- Use in-memory SQLite for test fixtures
- Each step: write code -> write tests -> run tests -> run linter -> review for safety

## Git Rules
- Never commit `.env` or secrets
- Keep commits focused and descriptive

## Roadmap
- [x] Project setup (structure, config, Docker, CI)
- [x] Umlaut utilities
- [x] Database layer with validation, logging, indexes
- [x] Logging & error handling infrastructure
- [ ] SM-2 spaced repetition algorithm
- [ ] Quiz logic (question generation, session management)
- [ ] Telegram handlers (commands, ConversationHandler for /add and /quiz)
- [ ] Main entry point
- [ ] AI-powered features (context sentences, grammar tips, smart corrections)
