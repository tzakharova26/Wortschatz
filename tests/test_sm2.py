from datetime import datetime, timedelta

import pytest

from bot.sm2 import (
    DEFAULT_EASINESS_FACTOR,
    MIN_EASINESS_FACTOR,
    QUALITY_CORRECT,
    QUALITY_WRONG,
    SM2State,
    calculate_sm2,
    sm2_from_db,
)


class TestCalculateSM2:
    def test_first_correct(self):
        now = datetime(2026, 5, 6, 12, 0, 0)
        state = SM2State()
        result = calculate_sm2(state, QUALITY_CORRECT, now=now)
        assert result.repetitions == 1
        assert result.interval == 1
        assert result.correct_count == 1
        assert result.next_review == now + timedelta(days=1)

    def test_second_correct(self):
        now = datetime(2026, 5, 6, 12, 0, 0)
        state = SM2State(repetitions=1, interval=1, correct_count=1)
        result = calculate_sm2(state, QUALITY_CORRECT, now=now)
        assert result.repetitions == 2
        assert result.interval == 6
        assert result.correct_count == 2
        assert result.next_review == now + timedelta(days=6)

    def test_third_correct(self):
        now = datetime(2026, 5, 6, 12, 0, 0)
        state = SM2State(easiness_factor=2.5, repetitions=2, interval=6, correct_count=2)
        result = calculate_sm2(state, QUALITY_CORRECT, now=now)
        assert result.repetitions == 3
        assert result.interval == round(6 * result.easiness_factor)
        assert result.correct_count == 3

    def test_wrong_resets_repetitions(self):
        now = datetime(2026, 5, 6, 12, 0, 0)
        state = SM2State(easiness_factor=2.5, repetitions=3, interval=15, correct_count=5)
        result = calculate_sm2(state, QUALITY_WRONG, now=now)
        assert result.repetitions == 0
        assert result.interval == 1
        assert result.correct_count == 5
        assert result.next_review == now + timedelta(days=1)

    def test_easiness_factor_decreases_on_wrong(self):
        state = SM2State(easiness_factor=2.5)
        result = calculate_sm2(state, QUALITY_WRONG)
        assert result.easiness_factor < 2.5

    def test_easiness_factor_increases_on_perfect(self):
        state = SM2State(easiness_factor=2.5)
        result = calculate_sm2(state, 5)
        assert result.easiness_factor > 2.5

    def test_easiness_factor_never_below_minimum(self):
        state = SM2State(easiness_factor=MIN_EASINESS_FACTOR)
        result = calculate_sm2(state, 0)
        assert result.easiness_factor >= MIN_EASINESS_FACTOR

    def test_easiness_factor_floor_after_many_wrongs(self):
        state = SM2State()
        for _ in range(20):
            state = calculate_sm2(state, 0)
        assert state.easiness_factor == MIN_EASINESS_FACTOR

    def test_next_review_with_explicit_now(self):
        now = datetime(2026, 1, 1, 0, 0, 0)
        state = SM2State()
        result = calculate_sm2(state, QUALITY_CORRECT, now=now)
        assert result.next_review == datetime(2026, 1, 2, 0, 0, 0)

    def test_next_review_defaults_to_now(self):
        before = datetime.now()
        state = SM2State()
        result = calculate_sm2(state, QUALITY_CORRECT)
        after = datetime.now()
        assert before + timedelta(days=1) <= result.next_review <= after + timedelta(days=1)

    def test_quality_3_is_correct(self):
        state = SM2State()
        result = calculate_sm2(state, 3)
        assert result.repetitions == 1
        assert result.correct_count == 1

    def test_quality_2_is_wrong(self):
        state = SM2State(repetitions=2, interval=6, correct_count=3)
        result = calculate_sm2(state, 2)
        assert result.repetitions == 0
        assert result.correct_count == 3

    def test_invalid_quality_too_high(self):
        with pytest.raises(ValueError, match="Quality must be 0-5"):
            calculate_sm2(SM2State(), 6)

    def test_invalid_quality_negative(self):
        with pytest.raises(ValueError, match="Quality must be 0-5"):
            calculate_sm2(SM2State(), -1)

    def test_long_sequence_correct(self):
        state = SM2State()
        intervals = []
        for _ in range(6):
            state = calculate_sm2(state, QUALITY_CORRECT)
            intervals.append(state.interval)
        assert intervals == sorted(intervals)
        assert state.correct_count == 6
        assert state.repetitions == 6

    def test_recovery_after_wrong(self):
        state = SM2State(repetitions=3, interval=15, correct_count=5)
        state = calculate_sm2(state, QUALITY_WRONG)
        assert state.repetitions == 0
        assert state.interval == 1
        state = calculate_sm2(state, QUALITY_CORRECT)
        assert state.repetitions == 1
        assert state.interval == 1
        state = calculate_sm2(state, QUALITY_CORRECT)
        assert state.repetitions == 2
        assert state.interval == 6

    def test_frozen_state(self):
        state = SM2State()
        with pytest.raises(AttributeError):
            state.easiness_factor = 1.0


class TestSM2FromDb:
    def test_from_none(self):
        state = sm2_from_db(None)
        assert state.easiness_factor == DEFAULT_EASINESS_FACTOR
        assert state.interval == 0
        assert state.repetitions == 0
        assert state.correct_count == 0
        assert state.next_review is None

    def test_from_row(self):
        row = {
            "easiness_factor": 2.3,
            "interval": 6,
            "repetitions": 2,
            "correct_count": 3,
            "next_review": "2026-05-10T12:00:00",
        }
        state = sm2_from_db(row)
        assert state.easiness_factor == 2.3
        assert state.interval == 6
        assert state.repetitions == 2
        assert state.correct_count == 3
        assert state.next_review == datetime(2026, 5, 10, 12, 0, 0)

    def test_from_row_null_next_review(self):
        row = {
            "easiness_factor": 2.5,
            "interval": 0,
            "repetitions": 0,
            "correct_count": 0,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.next_review is None

    def test_invalid_easiness_factor_clamped(self):
        row = {
            "easiness_factor": 0.5,
            "interval": 6,
            "repetitions": 2,
            "correct_count": 3,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.easiness_factor == MIN_EASINESS_FACTOR

    def test_none_easiness_factor_clamped(self):
        row = {
            "easiness_factor": None,
            "interval": 6,
            "repetitions": 2,
            "correct_count": 3,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.easiness_factor == MIN_EASINESS_FACTOR

    def test_negative_interval_reset(self):
        row = {
            "easiness_factor": 2.5,
            "interval": -3,
            "repetitions": 2,
            "correct_count": 3,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.interval == 0

    def test_negative_repetitions_reset(self):
        row = {
            "easiness_factor": 2.5,
            "interval": 6,
            "repetitions": -1,
            "correct_count": 3,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.repetitions == 0

    def test_negative_correct_count_reset(self):
        row = {
            "easiness_factor": 2.5,
            "interval": 6,
            "repetitions": 2,
            "correct_count": -5,
            "next_review": None,
        }
        state = sm2_from_db(row)
        assert state.correct_count == 0

    def test_invalid_next_review_string(self):
        row = {
            "easiness_factor": 2.5,
            "interval": 6,
            "repetitions": 2,
            "correct_count": 3,
            "next_review": "not-a-date",
        }
        state = sm2_from_db(row)
        assert state.next_review is None

    def test_missing_keys_use_defaults(self):
        row = {}
        state = sm2_from_db(row)
        assert state.easiness_factor == DEFAULT_EASINESS_FACTOR
        assert state.interval == 0
        assert state.repetitions == 0
        assert state.correct_count == 0
        assert state.next_review is None
