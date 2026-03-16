# PowerTimer v1.0.0

Release date: 2026-03-16

## Summary

First public portfolio release of PowerTimer, a Windows 11 desktop utility for scheduling power actions with multiple trigger types, optional Task Scheduler persistence, and post-execution verification.

## Highlights

- Multi-action support:
  - Shutdown, Restart, Sleep, Hibernate, Lock
  - Safe Mode restart variants (minimal / networking)
- Multi-trigger scheduling:
  - Countdown
  - Specific time (`HH:MM`)
  - Process exit
  - CPU / disk / network idle
  - User idle
- Reliability improvements:
  - Persisted task state
  - Atomic settings writes
  - Final abort countdown dialog
  - Fullscreen execution guard
- Operational improvements:
  - Rotating logs + in-app log viewer
  - Verification summary using Task Scheduler + Event Log signals
- Portfolio/release readiness:
  - Unit tests + UI/e2e tests (environment-aware)
  - CI, security scans, release workflow
  - MIT license, contribution and security docs

## What is included in this release

- Source code
- Windows build artifact (`PowerTimer-windows.zip`)
- SHA-256 checksum file (`SHA256SUMS.txt`)

## Known limitations

- Windows-only application
- Some actions require Administrator privileges (Safe Mode / `bcdedit`)
- UI/e2e tests may be skipped in environments without Tk runtime
- Verification of lock action depends on local audit policy availability

## Upgrade / install notes

1. Download and unpack `PowerTimer-windows.zip`
2. Run `PowerTimer.exe`
3. If you plan to use Safe Mode actions, run as Administrator

## Checks performed for this release

- `python -m unittest discover -s tests -v`
- `python -m compileall -q .`
- CI workflow green
- Security workflow green (`pip-audit`, `bandit`)
