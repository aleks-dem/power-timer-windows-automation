from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from core.models import ActiveTask, TaskConfig
from core.verify_execution import _parse_dt, _to_aware_local, verify_execution


def _make_task(
    action: str = "Shutdown",
    next_fire: str = "2026-01-01T12:00:00+00:00",
    scheduled_name: str | None = "PowerTimer_test",
) -> ActiveTask:
    cfg = TaskConfig(action=action, trigger="Countdown", seconds=30)
    return ActiveTask(
        task_id="test-task",
        created_at_iso="2026-01-01T11:59:00+00:00",
        status="active",
        config=cfg.to_dict(),
        next_fire_time_iso=next_fire,
        scheduled_task_name=scheduled_name,
    )


class TestVerifyExecution(unittest.TestCase):
    def test_parse_dt_supports_z_suffix_and_ps_json_date(self) -> None:
        z = _parse_dt("2026-01-01T12:00:00Z")
        ps = _parse_dt("/Date(0)/")
        self.assertIsNotNone(z)
        self.assertIsNotNone(ps)
        assert z is not None
        assert ps is not None
        self.assertIsNotNone(z.tzinfo)
        self.assertEqual(ps.tzinfo, dt.timezone.utc)

    def test_to_aware_local_returns_aware_datetime(self) -> None:
        naive = dt.datetime(2026, 1, 1, 12, 0, 0)
        aware = _to_aware_local(naive)
        self.assertIsNotNone(aware.tzinfo)

    def test_verify_execution_returns_yes_when_scheduler_reports_success(self) -> None:
        task = _make_task()
        with mock.patch(
            "core.verify_execution.get_scheduled_task_info",
            return_value={
                "LastRunTime": "2026-01-01T12:01:00+00:00",
                "LastTaskResult": 0,
                "NextRunTime": None,
                "NumberOfMissedRuns": 0,
            },
        ), mock.patch(
            "core.verify_execution._wevtutil_query_xml",
            return_value=None,
        ):
            res = verify_execution(logger=None, task=task)
        self.assertEqual(res.status, "yes")

    def test_verify_execution_returns_unknown_without_expected_time(self) -> None:
        task = _make_task(next_fire="", scheduled_name=None)
        task.fired_at_iso = None
        res = verify_execution(logger=None, task=task)
        self.assertEqual(res.status, "unknown")


if __name__ == "__main__":
    unittest.main()
