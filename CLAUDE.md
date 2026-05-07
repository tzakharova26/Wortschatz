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
    quiz.py            # Quiz logic, question generation (revision flow)
    learn.py           # Learning flow (massed drill for new words, graduation into SM-2)
    sm2.py             # SM-2 spaced repetition algorithm
    stats.py           # Statistics formatting
    umlaut.py          # Umlaut conversion utilities
    config.py          # Quiz session size, temperature, weights, list cap, etc.
    logging_config.py  # Centralized logging setup
  tests/
    __init__.py
    conftest.py        # Shared fixtures (in-memory DB, fake update/context)
    helpers.py         # Test helpers (e.g. graduate_word to seed /quiz pool)
    test_database.py
    test_sm2.py
    test_quiz.py
    test_learn.py
    test_umlaut.py
    test_handlers.py
    test_stats.py
    test_main.py
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

**Verbs -- irregular present (vi):**
```
vi <infinitive> <partizip_ii> <ich> <du> <er/sie/es> <translation>
```
Example: `vi fahren ist gefahren fahre faehrst faehrt to drive`
Stored as JSON in `irregular_forms`: `{"ich": "fahre", "du": "fährst", "er": "fährt"}`

The `vi` marker (instead of `v`) disambiguates irregular verbs from regular ones with multi-word translations like `v gehen ist gegangen to walk on foot`.

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

**Prepositions (prep):**
```
prep <word> <translation>
```
Example: `prep mit with (+dat)` — case info goes in the translation field.

### Field Separator
Each `/add` line can use **spaces** or **`|` (pipe)** as field separators (auto-detected per line). Pipe is recommended when translations contain spaces or for readability:
```
n | die Katze | Katzen | a small cat
vi | fahren | ist gefahren | fahre | faehrst | faehrt | to drive
```

### Input Validation
- `part_of_speech` (input markers) is one of: `n`, `v`, `vi`, `adj`, `adv`, `prep` (`vi` is parsed as irregular `v` and stored as `v`)
- Stored `part_of_speech` is one of: `n`, `v`, `adj`, `adv`, `prep`
- `german` and `translation` cannot be empty or whitespace-only
- All inputs are stripped of leading/trailing whitespace
- Tags are normalized: whitespace stripped, empty segments removed
- `quiz_type` must be one of: `translate`, `multiple_choice`, `article`, `verb_forms`

### Umlaut Handling
- Store and display proper Unicode (ae->ä, oe->ö, ue->ü, ss->ß where appropriate)
- Accept both ASCII and Unicode forms on input
- **Quiz answer matching (directional):**
  - User may simplify: ä→ae, ö→oe, ü→ue, ß→ss — always accepted
  - User must NOT add special chars where stored word doesn't have them: typing ä where stored is a = WRONG, typing ß where stored is ss = WRONG
  - Algorithm: expand both stored and user input (ä→ae, ß→ss etc.), compare. Additionally check that user's original input doesn't contain ä/ö/ü/ß at positions where stored word has plain a/o/u/ss

### Tags
- A word can have **multiple tags** (assigned across different `/add` sessions)
- Tags are optional, one tag per `/add` batch
- Stored as comma-separated string in `words.tags` column
- No default tag for untagged words

## Quiz System

### Quiz Config (`bot/config.py`)
```python
QUIZ_SESSION_SIZE = 7
QUIZ_TEMPERATURE = 0.3

QUIZ_TYPE_WEIGHTS = {
    "translate": 1.0,
    "verb_forms": 0.9,
    "multiple_choice": 0.6,
    "article": 0.5,
    "plural": 0.5,
}
```

### Quiz Types (mixed in one session)
1. **translate** -- bot shows translation, user types the German word (all POS). For nouns, user must include article.
2. **multiple_choice** -- bot shows German word + buttons with translation options; wrong options from same POS, fallback to all vocabulary. Buttons in Telegram.
3. **article** -- nouns only: bot shows noun without article, user picks der/die/das buttons.
4. **verb_forms** -- irregular verbs only: bot shows infinitive + which form to type (e.g. "du"), user types the form. Form is randomly picked from stored irregular_forms JSON.
5. **plural** -- nouns with a non-empty plural only: bot shows article + singular ("die Katze"), user types the plural form ("Katzen"). Typed input with umlaut tolerance.

### Multiple Choice Option Filling
1. Try same POS words from user's vocabulary (3 wrong options needed)
2. If < 3 same POS available, fill from any POS in user's vocabulary
3. If total words < 4, use whatever is available (even 2 options)

### Quiz Type Selection (Temperature-weighted)
For each word, select quiz type using weighted random:
- `weight = QUIZ_TYPE_WEIGHTS[quiz_type]`
- Each quiz type weight is temperatured by how long since the word was last reviewed (overall, not per quiz type):
  `score = (days_since_last_review + 1) ^ (1 / TEMPERATURE)`
  `final_weight = score * QUIZ_TYPE_WEIGHTS[quiz_type]`
- Low temperature (0.3) = long-unseen words dominate
- High temperature (1.0) = flatter distribution
- Never-reviewed words get a high default days_since value

### Self-Rating Buttons (Anki-style, 2 contextual + misspell)
After user answers and sees the correct answer, show 3 rating buttons. The two quality
buttons depend on whether the answer was correct:

If the answer was **correct**:
- `Good (4)` -- correct, normal effort
- `Easy (5)` -- correct, effortless
- `Misspell` -- knew the word but typo/spelling error; doesn't count, word re-added at end

If the answer was **wrong**:
- `Blackout (0)` -- no idea at all
- `Wrong (1)` -- got it wrong but somewhat remembered
- `Misspell` -- knew the word but typo/spelling error; doesn't count, word re-added at end

The quiz start message explains all five quality levels and the misspell behaviour.

### Session Flow
1. `/quiz` or `/quiz #tag` -> generate QuizSession -> send start message with rating explanation -> send first question
2. User answers (types text or taps button) -> show result (correct/wrong + correct answer) + rating buttons
3. User rates -> store rating, advance to next question
4. If "Misspell" tapped -> recalculate quiz type for the word, append new question at end
5. After last question -> show summary with congrats (e.g., "5/7 correct" + per-word breakdown)
6. Async bulk-update SM-2 state and quiz_history after session ends

### Session Data Model
```python
@dataclass
class QuizQuestion:
    word: dict
    quiz_type: str
    prompt: str              # text to show user
    options: list[str] | None  # for multiple_choice/article buttons, None for typed
    correct_answer: str
    verb_form_key: str | None  # "du", "er" etc. for verb_forms type

@dataclass
class QuizSession:
    user_id: int
    questions: list[QuizQuestion]
    current_index: int = 0
    results: list[tuple[int, bool] | None]  # (quality_rating, was_correct), or None for misspell
```

### SM-2 Spaced Repetition Algorithm
Full SM-2 implementation:
- Each word+quiz_type pair has its own SM-2 state (easiness factor, interval, repetitions)
- After each answer, SM-2 state updated with the user's self-rated quality (0-5)
- Words with earliest due date are prioritized for quiz selection

### Schema: Verb Forms as JSON
Replace `ich_form`, `du_form`, `er_form` columns with:
```sql
irregular_forms TEXT  -- JSON: {"ich": "fahre", "du": "faehrst", "er": "faehrt"}
```
Input format unchanged; positions parsed as ich, du, er by default. JSON storage is extensible for future forms.

### "Learned" Definition (for stats only)
A word is considered **learned** when all applicable quiz types have been passed at least **4 times total**:
- Noun: quizzes 1, 2, 3, 5 (translation, multiple choice, article, plural). Nouns without a plural skip 5.
- Regular verb: quizzes 1, 2 (translation, multiple choice)
- Irregular verb: quizzes 1, 2, 4 (translation, multiple choice, verb forms)
- Adjective/Adverb: quizzes 1, 2 (translation, multiple choice)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + commands + rating system explanation |
| `/help` | Interactive help with topic buttons (Commands / How to add / How quizzes work) |
| `/add [tag]` | Interactive: add word cards (batch, one per line). Tag is an optional command argument. |
| `/list <tag>` | List words filtered by tag. Tag is **required**; truncated to LIST_MAX_WORDS=40. |
| `/tags` | List all existing tags |
| `/delete <word>` | Delete a word card by its German text (umlaut-aware). Confirms via `/delete_confirm` if multiple matches. |
| `/quiz [N] [tag]` | Start a quiz: `N` questions (default 7, capped at QUIZ_MAX_SIZE=50), optional tag filter. Args order-independent. If due words < N, the session cycles through them with new quiz types. **Excludes words still in the `/learn` pool.** |
| `/learn [N] [tag]` | Massed-drill flow for new (or Blackout-flagged) words. Per word: show card → MC → typed → (article + plural for nouns / two verb forms for irregular verbs). Wrong steps retry once at session end; a word graduates only when all required steps pass. Graduation seeds SM-2 with synthetic Good ratings per applicable quiz type. Capped at `LEARN_MAX_SIZE=10`. |
| `/stats` | Show learning statistics (today / week / month / overall) |
| `/remindme HH:MM [tz]` | Add a daily quiz reminder. Default timezone is `Europe/Berlin`. Multiple reminders per user supported. |
| `/reminders` | List user's reminders with each one's source time and Berlin/Moscow equivalents. |
| `/remindoff <id\|all>` | Remove a specific reminder (by id) or all of them. |

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
    irregular_forms TEXT,            -- JSON: {"ich": "fahre", "du": "fährst", "er": "fährt"}
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
    last_quality INTEGER,           -- 0-5; NULL until first answer. last_quality=0 (Blackout) demotes word into /learn pool.
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

CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    hour INTEGER NOT NULL,                    -- 0-23
    minute INTEGER NOT NULL,                  -- 0-59
    timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',  -- IANA name
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reminders_user_id ON reminders(user_id);
```

## Reminders
- Multiple reminders per user (no UNIQUE constraint)
- Stored timezone is an IANA name; validated via `zoneinfo.ZoneInfo`
- Default timezone is `Europe/Berlin` when user omits it
- Daily firing handled by python-telegram-bot's `JobQueue` (requires `[job-queue]` extra → APScheduler)
- Each job is named `reminder_{id}` so it can be individually cancelled
- On every bot startup, `load_all_reminders` repopulates the JobQueue from the DB (jobs are in-memory only)
- Reminder messages: "Time to practice German! Send /quiz to start." Send failures (e.g., user blocked the bot) are caught and logged; the DB row is preserved so reminders resume if the user unblocks.
- `/reminders` displays both Berlin and Moscow times for each entry, regardless of source TZ; uses today's date as DST reference

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
- [x] SM-2 spaced repetition algorithm
- [x] Quiz logic (question generation, session management)
- [x] Telegram handlers (commands, ConversationHandler for /add and /quiz)
- [x] Main entry point
- [x] Pipe `|` separator for `/add`
- [x] Preview-and-confirm flow for `/add` (`ADD_CONFIRM` state, `/confirm`)
- [x] Tag merging on duplicate-word add
- [x] Preposition POS (`prep`)
- [x] Configurable quiz size (`/quiz [N] [tag]`) with cycling for small vocabularies
- [x] Daily reminders with multi-timezone support (`/remindme`, `/reminders`, `/remindoff`)
- [x] Learning flow (`/learn`): massed drill for brand-new and Blackout-flagged words; graduates into `/quiz` via synthetic Good rating; post-`/add` "Start learning" button; `last_quality` column on `sm2_state`
- [ ] AI-powered features (context sentences, grammar tips, smart corrections)
