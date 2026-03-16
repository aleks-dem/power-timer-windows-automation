from __future__ import annotations

import shutil
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock


def _install_optional_stubs() -> None:
    if "pystray" not in sys.modules:
        try:
            __import__("pystray")
        except Exception:
            pystray_mod = types.ModuleType("pystray")

            class Icon:
                def __init__(self, *args, **kwargs):
                    self.icon = kwargs.get("icon")
                    self.title = kwargs.get("title", "")

                def run(self):
                    return None

                def stop(self):
                    return None

            def MenuItem(*args, **kwargs):
                return (args, kwargs)

            def Menu(*items):
                return items

            pystray_mod.Icon = Icon
            pystray_mod.MenuItem = MenuItem
            pystray_mod.Menu = Menu
            sys.modules["pystray"] = pystray_mod

    try:
        __import__("PIL")
    except Exception:
        pil_mod = types.ModuleType("PIL")
        image_mod = types.ModuleType("PIL.Image")
        imagetk_mod = types.ModuleType("PIL.ImageTk")
        imagedraw_mod = types.ModuleType("PIL.ImageDraw")

        class _DummyImage:
            size = (64, 64)

            def resize(self, *_args, **_kwargs):
                return self

            def copy(self):
                return _DummyImage()

            def convert(self, *_args, **_kwargs):
                return self

            def save(self, *_args, **_kwargs):
                return None

        def _open(*_args, **_kwargs):
            return _DummyImage()

        def _new(*_args, **_kwargs):
            return _DummyImage()

        def _frombuffer(*_args, **_kwargs):
            return _DummyImage()

        class _PhotoImage:
            def __init__(self, *_args, **_kwargs):
                pass

        class _Draw:
            def ellipse(self, *_args, **_kwargs):
                return None

            def line(self, *_args, **_kwargs):
                return None

            def arc(self, *_args, **_kwargs):
                return None

        def _draw(*_args, **_kwargs):
            return _Draw()

        image_mod.open = _open
        image_mod.new = _new
        image_mod.frombuffer = _frombuffer
        image_mod.LANCZOS = 1
        imagetk_mod.PhotoImage = _PhotoImage
        imagedraw_mod.Draw = _draw

        pil_mod.Image = image_mod
        pil_mod.ImageTk = imagetk_mod
        pil_mod.ImageDraw = imagedraw_mod

        sys.modules["PIL"] = pil_mod
        sys.modules["PIL.Image"] = image_mod
        sys.modules["PIL.ImageTk"] = imagetk_mod
        sys.modules["PIL.ImageDraw"] = imagedraw_mod


_install_optional_stubs()

import ui.app as ui_app
from core.models import AppSettings


class _DummyTrayManager:
    def __init__(self, *args, **kwargs):
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _FakeScheduler:
    def __init__(self):
        self.started_with = None
        self._running = False

    def running(self) -> bool:
        return self._running

    def start(self, task) -> None:
        self.started_with = task
        self._running = True

    def stop(self) -> None:
        self._running = False


class TestUiE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path("tests") / ".tmp" / f"ui_e2e_{uuid.uuid4().hex}"
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.tmp_root / "settings.json"
        self.log_file = self.tmp_root / "powertimer.log"
        self.task_xml_dir = self.tmp_root / "_taskxml"

        self.patchers = [
            mock.patch.object(ui_app, "TrayManager", _DummyTrayManager),
            mock.patch.object(ui_app, "setup_logging", return_value=_DummyLogger()),
            mock.patch.object(ui_app, "create_show_event", return_value=None),
            mock.patch.object(ui_app, "wait_for_show_event", return_value=None),
            mock.patch.object(ui_app, "ensure_icon_file", return_value=None),
            mock.patch.object(ui_app, "load_icon_image", return_value=None),
            mock.patch.object(ui_app, "set_window_icons", return_value=None),
            mock.patch.object(ui_app, "settings_path", return_value=self.settings_file),
            mock.patch.object(ui_app, "log_path", return_value=self.log_file),
            mock.patch.object(ui_app, "tmp_task_xml_dir", return_value=self.task_xml_dir),
            mock.patch.object(ui_app, "load_settings", return_value=AppSettings.default()),
            mock.patch.object(ui_app, "load_active_task", return_value=None),
            mock.patch.object(ui_app, "save_ui_state", return_value=None),
            mock.patch.object(ui_app, "save_active_task", return_value=None),
            mock.patch.object(ui_app, "abort_shutdown", return_value=None),
            mock.patch.object(ui_app.messagebox, "showinfo", return_value=None),
            mock.patch.object(ui_app.messagebox, "showerror", return_value=None),
            mock.patch.object(ui_app.messagebox, "askyesno", return_value=True),
            mock.patch.object(ui_app.PowerTimerApp, "_poll_ui_queue", return_value=None),
            mock.patch.object(ui_app.PowerTimerApp, "_refresh_processes", return_value=None),
            mock.patch.object(ui_app.PowerTimerApp, "reload_logs", return_value=None),
        ]
        for p in self.patchers:
            p.start()

        try:
            self.app = ui_app.PowerTimerApp()
        except Exception as exc:
            for p in reversed(self.patchers):
                p.stop()
            shutil.rmtree(self.tmp_root, ignore_errors=True)
            self.skipTest(f"Tkinter UI environment is unavailable: {exc}")
        self.app.root.withdraw()
        self.app.scheduler = _FakeScheduler()
        self.app.proc_list = []

    def tearDown(self) -> None:
        try:
            self.app.root.destroy()
        except Exception:
            pass
        for p in reversed(self.patchers):
            p.stop()
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_start_countdown_creates_active_task_and_starts_scheduler(self) -> None:
        self.app.trigger_var.set("Countdown")
        self.app.count_val.set("2")
        self.app.count_unit.set("minutes")

        self.app.start_task()

        self.assertIsNotNone(self.app.active_task)
        self.assertIs(self.app.scheduler.started_with, self.app.active_task)
        self.assertTrue(self.app.scheduler.running())

    def test_start_with_invalid_time_shows_error(self) -> None:
        self.app.trigger_var.set("At time (HH:MM)")
        self.app.at_time_var.set("99:77")

        with mock.patch.object(ui_app.messagebox, "showerror") as showerror:
            self.app.start_task()

        self.assertIsNone(self.app.scheduler.started_with)
        showerror.assert_called()

    def test_start_after_app_exits_without_pid_shows_error(self) -> None:
        self.app.trigger_var.set("After app exits")
        self.app.proc_var.set("")

        with mock.patch.object(ui_app.messagebox, "showerror") as showerror:
            self.app.start_task()

        self.assertIsNone(self.app.scheduler.started_with)
        showerror.assert_called()


if __name__ == "__main__":
    unittest.main()
