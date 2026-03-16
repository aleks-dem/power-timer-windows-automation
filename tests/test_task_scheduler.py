from __future__ import annotations

import datetime as dt
import unittest

from core.task_scheduler import ScheduledTaskSpec, _local_iso_with_offset, build_task_xml


class TestTaskScheduler(unittest.TestCase):
    def test_local_iso_without_offset_format(self) -> None:
        t = dt.datetime(2026, 1, 2, 3, 4, 5)
        stamp = _local_iso_with_offset(t)
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_build_task_xml_escapes_command_and_metadata(self) -> None:
        spec = ScheduledTaskSpec(
            name="PowerTimer_Test",
            run_at=dt.datetime.now().astimezone() + dt.timedelta(minutes=5),
            command=r'shutdown /s /t 0 & echo "<tag>"',
            author='Me & "Team"',
            description="Demo <desc>",
        )
        xml = build_task_xml(spec)
        self.assertIn("&amp;", xml)
        self.assertIn("&lt;tag&gt;", xml)
        self.assertIn("&lt;desc&gt;", xml)


if __name__ == "__main__":
    unittest.main()
