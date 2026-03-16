from __future__ import annotations

import unittest

from core.models import ActiveTask, TaskConfig


class TestModels(unittest.TestCase):
    def test_task_config_from_dict_ignores_unknown_fields(self) -> None:
        cfg = TaskConfig.from_dict(
            {
                "action": "Restart",
                "seconds": 42,
                "unknown_field": "ignored",
            }
        )
        self.assertEqual(cfg.action, "Restart")
        self.assertEqual(cfg.seconds, 42)
        self.assertFalse(hasattr(cfg, "unknown_field"))

    def test_active_task_new_initializes_expected_defaults(self) -> None:
        cfg = TaskConfig(action="Lock", trigger="Countdown", seconds=10)
        task = ActiveTask.new(cfg)
        self.assertEqual(task.status, "active")
        self.assertEqual(task.phase, "waiting")
        self.assertEqual(task.config["action"], "Lock")
        self.assertTrue(task.task_id)


if __name__ == "__main__":
    unittest.main()
