from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.models import AppSettings, ActiveTask


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings.default()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppSettings.default()

    ui = data.get("ui", {}) or {}
    active_task = data.get("active_task")
    if active_task is not None and not isinstance(active_task, dict):
        active_task = None
    return AppSettings(ui=ui, active_task=active_task)


def save_settings(path: Path, settings: AppSettings) -> None:
    atomic_write_json(path, settings.to_dict())


def load_active_task(path: Path) -> Optional[ActiveTask]:
    s = load_settings(path)
    if not s.active_task:
        return None
    try:
        return ActiveTask.from_dict(s.active_task)
    except Exception:
        return None


def save_active_task(path: Path, task: Optional[ActiveTask]) -> None:
    s = load_settings(path)
    s.active_task = task.to_dict() if task else None
    save_settings(path, s)


def save_ui_state(path: Path, ui: Dict[str, Any]) -> None:
    s = load_settings(path)
    s.ui = ui
    save_settings(path, s)
