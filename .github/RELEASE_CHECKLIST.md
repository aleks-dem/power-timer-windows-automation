# Release Checklist

Use this checklist before creating a public release.

## Code quality

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] UI/e2e tests status reviewed (if skipped, reason documented)
- [ ] `python -m compileall -q .` passes
- [ ] Manual smoke test on Windows 11 completed

## Security and dependencies

- [ ] Security workflow is green (`pip-audit` + `bandit`)
- [ ] Lockfiles updated when dependencies changed
- [ ] No secrets in repo (`gitleaks`/manual scan)

## Documentation

- [ ] `README.md` reflects current features and build instructions
- [ ] `THIRD_PARTY_NOTICES.md` reviewed
- [ ] `SECURITY.md` contact channels are valid

## Build and artifacts

- [ ] Tag prepared as `vX.Y.Z`
- [ ] Release workflow produced `PowerTimer-windows.zip`
- [ ] `SHA256SUMS.txt` attached to release
- [ ] Release notes include key changes and known limitations

## Publish

- [ ] GitHub Release published from tag
- [ ] Quick post-release install/run sanity check completed
