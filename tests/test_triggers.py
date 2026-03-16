from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from core import triggers


class _FixedDateTime(dt.datetime):
    fixed_now = dt.datetime(2026, 1, 1, 23, 58, 0, tzinfo=dt.timezone.utc).astimezone()

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls.fixed_now
        return cls.fixed_now.astimezone(tz)


class TestTriggers(unittest.TestCase):
    def test_countdown_fire_time_is_not_in_the_past(self) -> None:
        start = dt.datetime.now().astimezone()
        fire = triggers.compute_fire_time_for_countdown(-5)
        self.assertGreaterEqual(fire, start)

    def test_at_hhmm_moves_to_next_day_when_time_passed(self) -> None:
        with mock.patch("core.triggers.dt.datetime", _FixedDateTime):
            now_local = _FixedDateTime.fixed_now
            past_hhmm = (now_local - dt.timedelta(minutes=1)).strftime("%H:%M")
            fire = triggers.compute_fire_time_for_at_hhmm(past_hhmm)
        self.assertEqual((fire.date() - _FixedDateTime.fixed_now.date()).days, 1)

    def test_at_hhmm_same_day_for_future_time(self) -> None:
        with mock.patch("core.triggers.dt.datetime", _FixedDateTime):
            now_local = _FixedDateTime.fixed_now
            future_hhmm = (now_local + dt.timedelta(minutes=1)).strftime("%H:%M")
            fire = triggers.compute_fire_time_for_at_hhmm(future_hhmm)
        self.assertEqual((fire.date() - _FixedDateTime.fixed_now.date()).days, 0)


if __name__ == "__main__":
    unittest.main()
