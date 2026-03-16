from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

from core.models import TaskConfig


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def set_suspend_state(hibernate: bool) -> None:
    powrprof = ctypes.WinDLL("PowrProf.dll")
    SetSuspendState = powrprof.SetSuspendState
    SetSuspendState.argtypes = [wintypes.BOOL, wintypes.BOOL, wintypes.BOOL]
    SetSuspendState.restype = wintypes.BOOL
    ok = SetSuspendState(bool(hibernate), True, False)
    if not ok:
        raise RuntimeError("SetSuspendState failed (sleep/hibernate may be disabled or unsupported).")


def run_shutdown(mode: str, force_close: bool) -> None:
    if mode == "shutdown":
        cmd = ["shutdown", "/s", "/t", "0"]
    elif mode == "restart":
        cmd = ["shutdown", "/r", "/t", "0"]
    elif mode == "hibernate":
        cmd = ["shutdown", "/h"]
    else:
        raise ValueError("Unknown shutdown mode")
    if force_close and mode in ("shutdown", "restart"):
        cmd.insert(1, "/f")
    subprocess.run(cmd, check=False)


def abort_shutdown() -> None:
    # Cancels a pending shutdown if any
    subprocess.run(["shutdown", "/a"], check=False)


def set_safeboot(kind: str) -> None:
    if not is_admin():
        raise PermissionError("Safe Mode reboot requires Administrator privileges (bcdedit).")
    subprocess.run(["bcdedit", "/set", "{current}", "safeboot", kind], check=True)


def clear_safeboot() -> bool:
    if not is_admin():
        raise PermissionError("Clearing SafeBoot requires Administrator privileges (bcdedit).")
    # Avoid failing when safeboot is already absent by checking first.
    enum = subprocess.run(
        ["bcdedit", "/enum", "{current}"],
        check=True,
        capture_output=True,
        text=True,
    )
    if "safeboot" not in (enum.stdout or "").lower():
        return False
    subprocess.run(["bcdedit", "/deletevalue", "{current}", "safeboot"], check=True)
    return True


def execute_action(cfg: TaskConfig) -> None:
    a = cfg.action

    if a == "Shutdown":
        run_shutdown("shutdown", cfg.force_close_apps)
    elif a == "Restart":
        run_shutdown("restart", cfg.force_close_apps)
    elif a == "Sleep":
        set_suspend_state(hibernate=False)
    elif a == "Hibernate":
        # Prefer official shutdown /h for deterministic hibernate behavior
        run_shutdown("hibernate", False)
    elif a == "Lock":
        lock_workstation()
    elif a == "Restart (Safe Mode minimal)":
        set_safeboot("minimal")
        run_shutdown("restart", cfg.force_close_apps)
    elif a == "Restart (Safe Mode + Networking)":
        set_safeboot("network")
        run_shutdown("restart", cfg.force_close_apps)
    else:
        raise ValueError(f"Unknown action: {a}")
