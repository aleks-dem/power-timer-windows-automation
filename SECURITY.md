# Security Policy

## Supported versions

This is currently a single active branch project. Security fixes are applied on `main`.

## Reporting a vulnerability

Please do **not** open a public issue for security vulnerabilities.

Use one of these channels:
- GitHub private security advisory (preferred)
- Private email contact listed in repository profile (optional secondary channel)

Please include:
- Affected version/commit
- Reproduction steps
- Expected vs actual behavior
- Impact assessment

## Response targets

- Initial acknowledgment: within 72 hours
- Triage decision: within 7 days
- Fix timeline: depends on severity and complexity

## Security practices in this repo

- Dependency vulnerability audit in CI (`pip-audit`)
- Static security scan in CI (`bandit`)
- Weekly dependency update checks via Dependabot
