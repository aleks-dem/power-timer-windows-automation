# PowerTimer Developer Guide

This guide is intentionally short and focused on practical contribution workflow.

## 1. Prerequisites

- Windows 11
- Python 3.11+
- PowerShell

## 2. Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock.txt
pip install -r requirements-dev.lock.txt
```

## 3. Run locally

```powershell
python main.py
```

## 4. Run tests

```powershell
python -m unittest discover -s tests -v
```

## 5. Build executable

### Reproducible build (spec-based)

```powershell
pyinstaller --noconfirm --clean PowerTimer.spec
```

Result:
- `dist/PowerTimer/PowerTimer.exe`

### One-file build

```powershell
pyinstaller --noconfirm --clean --windowed --onefile --name PowerTimer --icon app.ico main.py
```

Result:
- `dist/PowerTimer.exe`

## 6. Core implementation notes

- `ui/app.py` orchestrates user flows and scheduler callbacks.
- `core/scheduler.py` runs all trigger waits off the UI thread.
- `core/task_scheduler.py` is only for deterministic survive-exit triggers.
- `core/verify_execution.py` is best-effort evidence aggregation, not hard proof.

## 7. Common troubleshooting

- Safe Mode actions fail:
  - run app as Administrator (`bcdedit` requires elevated rights)

- Tray icon not visible:
  - verify `pystray`/`Pillow` installed in active environment

- Verification shows `unknown`:
  - Event Log access/auditing may be restricted on the machine

## 8. Suggested contribution workflow

1. Add or update tests first for behavior changes.
2. Keep UI thread free of blocking operations.
3. Persist user-visible state transitions in `ActiveTask`.
4. Validate external command paths and error messages.
