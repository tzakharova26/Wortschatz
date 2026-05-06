from dataclasses import dataclass
from datetime import datetime, timedelta

from bot.logging_config import get_logger, log_user_warning

MIN_EASINESS_FACTOR = 1.3
DEFAULT_EASINESS_FACTOR = 2.5

# Quality scores for our bot
QUALITY_CORRECT = 4
QUALITY_WRONG = 1

logger = get_logger(__name__)


@dataclass(frozen=True)
class SM2State:
    easiness_factor: float = DEFAULT_EASINESS_FACTOR
    interval: int = 0  # days
    repetitions: int = 0
    correct_count: int = 0
    next_review: datetime | None = None


def calculate_sm2(state: SM2State, quality: int, now: datetime | None = None) -> SM2State:
    """Apply the SM-2 algorithm and return a new state.

    quality: 0-5 (0 = complete blackout, 5 = perfect recall)
    now: current datetime (defaults to datetime.now() if not provided)
    """
    if not 0 <= quality <= 5:
        raise ValueError(f"Quality must be 0-5, got {quality}")

    if now is None:
        now = datetime.now()

    ef = state.easiness_factor
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(ef, MIN_EASINESS_FACTOR)

    if quality >= 3:
        correct_count = state.correct_count + 1
        repetitions = state.repetitions + 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = round(state.interval * ef)
    else:
        correct_count = state.correct_count
        repetitions = 0
        interval = 1

    next_review = now + timedelta(days=interval)

    return SM2State(
        easiness_factor=ef,
        interval=interval,
        repetitions=repetitions,
        correct_count=correct_count,
        next_review=next_review,
    )


def sm2_from_db(row: dict | None, user_id: int = 0) -> SM2State:
    """Create SM2State from a database row, or return default state."""
    if row is None:
        return SM2State()

    ef = row.get("easiness_factor", DEFAULT_EASINESS_FACTOR)
    if not isinstance(ef, (int, float)) or ef < MIN_EASINESS_FACTOR:
        log_user_warning(logger, user_id, f"Invalid easiness_factor={ef!r}, clamping to minimum")
        ef = MIN_EASINESS_FACTOR

    interval = row.get("interval", 0)
    if not isinstance(interval, int) or interval < 0:
        log_user_warning(logger, user_id, f"Invalid interval={interval!r}, resetting to 0")
        interval = 0

    repetitions = row.get("repetitions", 0)
    if not isinstance(repetitions, int) or repetitions < 0:
        log_user_warning(logger, user_id, f"Invalid repetitions={repetitions!r}, resetting to 0")
        repetitions = 0

    correct_count = row.get("correct_count", 0)
    if not isinstance(correct_count, int) or correct_count < 0:
        log_user_warning(
            logger, user_id, f"Invalid correct_count={correct_count!r}, resetting to 0"
        )
        correct_count = 0

    next_review = None
    raw_review = row.get("next_review")
    if raw_review is not None:
        try:
            next_review = datetime.fromisoformat(raw_review)
        except (ValueError, TypeError):
            log_user_warning(
                logger, user_id, f"Invalid next_review={raw_review!r}, resetting to None"
            )

    return SM2State(
        easiness_factor=ef,
        interval=interval,
        repetitions=repetitions,
        correct_count=correct_count,
        next_review=next_review,
    )
