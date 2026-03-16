from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if not base:
        base = str(Path.home())
    p = Path(base) / "PowerTimer"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return data_dir() / "settings.json"


def log_path() -> Path:
    return data_dir() / "powertimer.log"


def tmp_task_xml_dir() -> Path:
    return data_dir() / "_taskxml"


def icon_cache_path() -> Path:
    return data_dir() / "app.ico"
