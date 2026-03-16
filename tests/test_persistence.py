from __future__ import annotations

import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.models import ActiveTask, AppSettings, TaskConfig
from core.persistence import (
    load_active_task,
    load_settings,
    save_active_task,
    save_settings,
    save_ui_state,
)


@contextmanager
def _local_temp_dir():
    root = Path("tests") / ".tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestPersistence(unittest.TestCase):
    def test_save_and_load_settings_roundtrip(self) -> None:
        with _local_temp_dir() as tmp:
            path = tmp / "settings.json"
            settings = AppSettings(ui={"trigger": "Countdown"}, active_task=None)
            save_settings(path, settings)

            loaded = load_settings(path)
            self.assertEqual(loaded.ui.get("trigger"), "Countdown")
            self.assertIsNone(loaded.active_task)

    def test_save_and_load_active_task_roundtrip(self) -> None:
        with _local_temp_dir() as tmp:
            path = tmp / "settings.json"
            task = ActiveTask.new(TaskConfig(action="Shutdown", seconds=30))
            save_active_task(path, task)

            loaded_task = load_active_task(path)
            self.assertIsNotNone(loaded_task)
            assert loaded_task is not None
            self.assertEqual(loaded_task.task_id, task.task_id)
            self.assertEqual(loaded_task.config["action"], "Shutdown")

    def test_load_settings_invalid_json_returns_default(self) -> None:
        with _local_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text("{not valid json", encoding="utf-8")

            loaded = load_settings(path)
            self.assertEqual(loaded.ui, {})
            self.assertIsNone(loaded.active_task)

    def test_save_ui_state_preserves_active_task(self) -> None:
        with _local_temp_dir() as tmp:
            path = tmp / "settings.json"
            task = ActiveTask.new(TaskConfig(action="Restart", seconds=60))
            save_active_task(path, task)
            save_ui_state(path, {"action": "Restart"})

            loaded_task = load_active_task(path)
            self.assertIsNotNone(loaded_task)
            assert loaded_task is not None
            self.assertEqual(loaded_task.task_id, task.task_id)


if __name__ == "__main__":
    unittest.main()
