from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional, Tuple
import psutil

RECT = wintypes.RECT

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _get_foreground_hwnd() -> int:
    return ctypes.windll.user32.GetForegroundWindow()


def _is_iconic(hwnd: int) -> bool:
    return bool(ctypes.windll.user32.IsIconic(hwnd))


def _get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _get_window_title(hwnd: int) -> str:
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_rect_visible(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        rect = RECT()
        res = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if res == 0:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass

    rect = RECT()
    if ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def _get_monitor_rect_for_window(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    MONITOR_DEFAULTTONEAREST = 2
    hmon = ctypes.windll.user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    r = mi.rcMonitor
    return r.left, r.top, r.right, r.bottom


def foreground_is_fullscreen(tolerance_px: int = 2) -> Tuple[bool, str]:
    hwnd = _get_foreground_hwnd()
    if not hwnd or _is_iconic(hwnd):
        return False, ""

    rect = _get_window_rect_visible(hwnd)
    mrect = _get_monitor_rect_for_window(hwnd)
    if not rect or not mrect:
        return False, ""

    l, t, r, b = rect
    ml, mt, mr, mb = mrect

    covers = (
        abs(l - ml) <= tolerance_px and
        abs(t - mt) <= tolerance_px and
        abs(r - mr) <= tolerance_px and
        abs(b - mb) <= tolerance_px
    )
    if not covers:
        return False, ""

    pid = _get_window_pid(hwnd)
    title = _get_window_title(hwnd).strip()
    pname = ""
    try:
        pname = psutil.Process(pid).name()
    except Exception:
        pass

    ignore = {"explorer.exe", "dwm.exe", "ShellExperienceHost.exe", "SearchHost.exe"}
    if pname.lower() in ignore and not title:
        return False, ""

    desc = f"{pname or 'process'} (PID {pid})" + (f" — {title}" if title else "")
    return True, desc
