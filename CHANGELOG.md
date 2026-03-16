# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.
Versioning uses Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]

### Added

- 

### Changed

- 

### Fixed

- 

### Security

- 

## [1.0.0] - 2026-03-16

### Added

- Initial public release of PowerTimer (Windows desktop utility).
- Scheduler with multiple trigger types: countdown, fixed time, process exit, CPU/disk/network idle, user idle.
- Action execution support for shutdown/restart/sleep/hibernate/lock and Safe Mode restart variants.
- Survive-exit mode via Windows Task Scheduler for deterministic triggers.
- Verification flow using Task Scheduler metadata and Event Log evidence.
- Rotating log subsystem and in-app log viewer.
- Unit test suite and UI/e2e tests (with environment-aware skipping when Tk runtime is unavailable).
- GitHub CI workflow, security scanning workflow, release workflow.
- Governance files: `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, release checklist.
- Third-party notices and pinned dependency lockfiles.

### Changed

- Portfolio-focused documentation (`README`, module/architecture docs, guide).
- Startup validation for invalid `HH:MM`, missing process selection, and Safe Mode privilege checks.

### Fixed

- Correct default computation for `At time` (`now + 5 minutes` rollover-safe).
- Timezone normalization and cleanup in verification logic.
- Atomic JSON persistence now ensures parent directory creation.
- Cleanup of duplicate imports and non-project artifact comments.

### Security

- Added dependency vulnerability scanning (`pip-audit`) in CI.
- Added static security scanning (`bandit`) in CI.
- Added weekly Dependabot checks for `pip` and GitHub Actions.

---

## Template for next release

Copy this section, replace `X.Y.Z` and date:

## [X.Y.Z] - YYYY-MM-DD

### Added

- 

### Changed

- 

### Fixed

- 

### Security

- 
