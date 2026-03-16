# Third-Party Notices

This project depends on third-party packages. The list below is a practical summary for repository publication.

| Package | Role | License (summary) | Verification status |
|---|---|---|---|
| `psutil` | system/process metrics for triggers | BSD-3-Clause | verified from local package metadata |
| `pywin32-ctypes` | Windows API wrappers | BSD-3-Clause | verified from local package metadata |
| `pystray` | tray icon integration | MIT (per upstream project) | inferred (package metadata unavailable in this env) |
| `Pillow` | icon/image handling | PIL Software License / HPND-style permissive terms | inferred (package metadata unavailable in this env) |
| `pyinstaller` (dev) | EXE packaging | GPLv2+ with PyInstaller exception | verified from local package metadata |

## Notes

- `pyinstaller` is a build tool and not a runtime dependency of the app itself.
- The PyInstaller exception permits distributing generated executables.
- Before public release, run a dependency-license scan in your release environment to confirm exact package versions:

```powershell
python -m pip install pip-licenses
pip-licenses --from=mixed --format=markdown
```
