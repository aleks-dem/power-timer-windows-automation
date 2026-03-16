# PowerTimer Module Map

This file is a concise module-level reference for maintainers and reviewers.

## Entry point

- `main.py`
  - Windows-only guard
  - single-instance mutex/event behavior
  - app bootstrap (`PowerTimerApp`)

## Core (`core/`)

- `core/models.py`
  - `TaskConfig`: immutable-like runtime configuration model
  - `ActiveTask`: persisted task state, execution/verification metadata
  - `AppSettings`: UI + active task persistence envelope

- `core/persistence.py`
  - Atomic JSON writes (`.tmp` + replace)
  - Save/load UI state and active task

- `core/scheduler.py`
  - Background worker (`Scheduler`) for trigger waiting and action execution
  - Final abort countdown integration
  - Callback-based communication with UI

- `core/triggers.py`
  - Trigger waiters: countdown/clock/process exit/cpu/disk/network/user idle
  - Trigger utility functions to compute next fire time

- `core/actions.py`
  - Windows action execution wrappers (`shutdown`, sleep/hibernate, lock)
  - Safe mode setup/cleanup via `bcdedit`

- `core/task_scheduler.py`
  - Task Scheduler XML builder
  - `schtasks` create/delete/query helpers
  - Survive-exit registration support

- `core/verify_execution.py`
  - Best-effort post-run verification using Task Scheduler + Event Log evidence
  - Returns normalized verification states (`yes/likely/no/unknown`)

## UI (`ui/`)

- `ui/app.py`
  - Main Tkinter application
  - Configuration forms, validation, task lifecycle controls
  - Persistence restore, tray integration, verification summary UI

- `ui/dialogs.py`
  - `AbortDialog` during final execution countdown

- `ui/tray.py`
  - `TrayManager` wrapper around `pystray`
  - Context menu actions (show, cancel, exit)

## Utility (`util/`)

- `util/timefmt.py`: human-readable `HH:MM:SS` formatting
- `util/paths.py`: app-local paths under `%LOCALAPPDATA%\PowerTimer`
- `util/logutil.py`: rotating logs + tail/clear helpers + UI handler
- `util/single_instance.py`: named mutex + show-window event signaling
- `util/icon_data.py`: icon discovery/cache/extraction + window icon setup

## Windows helpers (`win/`)

- `win/idle.py`: user idle time via `GetLastInputInfo`
- `win/fullscreen.py`: foreground fullscreen detection with monitor/window geometry checks

## Testing coverage (high level)

- `tests/test_models.py`: model behaviors and defaults
- `tests/test_persistence.py`: JSON persistence and active-task integrity
- `tests/test_triggers.py`: deterministic fire-time rules
- `tests/test_task_scheduler.py`: XML generation and escaping
- `tests/test_verify_execution.py`: date parsing and verification decisions
