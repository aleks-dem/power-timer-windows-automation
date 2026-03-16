from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import uuid
import datetime as dt


ACTIONS = (
    "Shutdown",
    "Restart",
    "Sleep",
    "Hibernate",
    "Lock",
    "Restart (Safe Mode minimal)",
    "Restart (Safe Mode + Networking)",
)

TRIGGERS = (
    "Countdown",
    "At time (HH:MM)",
    "After app exits",
    "CPU low for N seconds",
    "Disk low for N seconds",
    "User idle for N minutes",
    "Network idle for N seconds",
)


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


@dataclass
class TaskConfig:
    # common
    action: str = "Shutdown"
    force_close_apps: bool = True
    block_fullscreen: bool = True
    survive_exit: bool = False  # Task Scheduler

    trigger: str = "Countdown"

    # Countdown
    seconds: int = 1800

    # At time
    at_hhmm: str = "23:00"

    # After app exits
    target_pid: Optional[int] = None
    process_delay_seconds: int = 0  # NEW: delay after process exits

    # CPU low
    cpu_threshold: float = 10.0
    cpu_duration_s: int = 120

    # Disk low
    disk_kbps_threshold: float = 200.0
    disk_duration_s: int = 120

    # Idle
    idle_minutes: int = 15

    # Network
    net_kbps_threshold: float = 30.0
    net_duration_s: int = 90

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskConfig":
        cfg = TaskConfig()
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


@dataclass
class ActiveTask:
    task_id: str
    created_at_iso: str
    status: str  # active | canceled | completed | stale
    config: Dict[str, Any]
    phase: str = "waiting"  # waiting | counting | armed | firing
    next_fire_time_iso: Optional[str] = None
    remaining_seconds: Optional[int] = None

    scheduled_task_name: Optional[str] = None  # Task Scheduler name (if survive_exit)
    note: str = ""
    
    fired_at_iso: Optional[str] = None
    verified_status: Optional[str] = None      # yes | likely | no | unknown
    verified_details: Optional[list[str]] = None

    @staticmethod
    def new(cfg: TaskConfig) -> "ActiveTask":
        tid = str(uuid.uuid4())
        return ActiveTask(
            task_id=tid,
            created_at_iso=now_local().isoformat(),
            status="active",
            config=cfg.to_dict(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActiveTask":
        return ActiveTask(
            task_id=d.get("task_id", ""),
            created_at_iso=d.get("created_at_iso", ""),
            status=d.get("status", "stale"),
            config=d.get("config", {}) or {},
            phase=d.get("phase", "waiting"),
            next_fire_time_iso=d.get("next_fire_time_iso"),
            remaining_seconds=d.get("remaining_seconds"),
            scheduled_task_name=d.get("scheduled_task_name"),
            note=d.get("note", ""),
            fired_at_iso=d.get("fired_at_iso"),
            verified_status=d.get("verified_status"),
            verified_details=d.get("verified_details"),
        )


@dataclass
class AppSettings:
    ui: Dict[str, Any]
    active_task: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {"ui": self.ui, "active_task": self.active_task}

    @staticmethod
    def default() -> "AppSettings":
        return AppSettings(ui={}, active_task=None)
