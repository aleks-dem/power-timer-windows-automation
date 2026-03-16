# Contributing Guide

Thanks for your interest in contributing.

## 1. Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock.txt
pip install -r requirements-dev.lock.txt
```

## 2. Run checks locally

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

When dependencies change:

```powershell
.\scripts\update_lockfiles.ps1
```

## 3. Pull request checklist

- Keep changes focused and small
- Add/update tests for behavior changes
- Keep Windows-specific behavior explicit in code/comments
- If `requirements*.txt` changed, regenerate lockfiles
- Update docs when user-visible behavior changes

## 4. Commit style

Recommended format:

```text
type(scope): short summary
```

Examples:
- `fix(scheduler): validate HH:MM before starting task`
- `test(ui): add e2e start/cancel flow checks`
- `docs(readme): add release and security sections`

## 5. Branching

- Create feature branches from `main`
- Open PR into `main`
- Squash merge is recommended for small repos

## 6. Release process

See [RELEASE_CHECKLIST.md](.github/RELEASE_CHECKLIST.md).
