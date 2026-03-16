from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional, Callable


ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
EVENT_MODIFY_STATE = 0x0002

SINGLE_INSTANCE_NAME = "Local\\PowerTimerSingleton"
SHOW_EVENT_NAME = "Local\\PowerTimerShow"


def acquire_single_instance(name: str) -> Optional[int]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def release_single_instance(handle: Optional[int]) -> None:
    if not handle:
        return
    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))


def create_show_event(name: str) -> Optional[int]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    handle = kernel32.CreateEventW(None, False, False, name)
    if not handle:
        return None
    return int(handle)


def signal_show_event(name: str) -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def wait_for_show_event(handle: int, on_signal: Callable[[], None]) -> None:
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    while True:
        res = kernel32.WaitForSingleObject(wintypes.HANDLE(handle), INFINITE)
        if res != WAIT_OBJECT_0:
            return
        on_signal()


def close_handle(handle: Optional[int]) -> None:
    if not handle:
        return
    ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))


def show_already_running(message: str, title: str = "PowerTimer") -> None:
    user32 = ctypes.windll.user32
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = wintypes.INT
    user32.MessageBoxW(None, message, title, 0x00000040)
