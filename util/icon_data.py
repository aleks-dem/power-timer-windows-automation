from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional

from util.paths import icon_cache_path

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow missing
    Image = None  # type: ignore


def find_app_icon_path() -> Optional[Path]:
    candidates: list[Path] = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(Path(base) / "app.ico")
    candidates.append(Path(sys.executable).resolve().parent / "app.ico")
    candidates.append(Path(__file__).resolve().parents[1] / "app.ico")
    for p in candidates:
        if p.exists():
            return p
    return None


def ensure_icon_file() -> Optional[Path]:
    # Prefer packaged/app.ico, but ensure a stable copy in writable user data.
    src = find_app_icon_path()
    cache = icon_cache_path()
    if src:
        try:
            if not cache.exists() or cache.read_bytes() != src.read_bytes():
                cache.write_bytes(src.read_bytes())
            return cache
        except Exception:
            return src
    img = _extract_icon_from_exe()
    if img is not None and Image is not None:
        try:
            img.save(
                cache,
                format="ICO",
                sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
            )
            return cache
        except Exception:
            pass
    return None


def set_window_icons(hwnd: int) -> None:
    p = ensure_icon_file()
    if not p:
        return
    try:
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        def _load_icon(size: int):
            return user32.LoadImageW(0, str(p), IMAGE_ICON, size, size, LR_LOADFROMFILE)

        small = _load_icon(16)
        big = _load_icon(32)
        if not big:
            big = _load_icon(64)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
    except Exception:
        pass


def _extract_icon_from_exe() -> Optional["Image.Image"]:
    if Image is None:
        return None
    try:
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        large = wintypes.HICON()
        small = wintypes.HICON()
        count = shell32.ExtractIconExW(str(sys.executable), 0, ctypes.byref(large), ctypes.byref(small), 1)
        if count == 0:
            return None
        hicon = large if large else small
        if not hicon:
            return None

        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon", wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP),
            ]

        class BITMAP(ctypes.Structure):
            _fields_ = [
                ("bmType", wintypes.LONG),
                ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD),
                ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        iconinfo = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(iconinfo)):
            user32.DestroyIcon(hicon)
            return None

        bmp = BITMAP()
        if not gdi32.GetObjectW(iconinfo.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bmp)):
            gdi32.DeleteObject(iconinfo.hbmColor)
            gdi32.DeleteObject(iconinfo.hbmMask)
            user32.DestroyIcon(hicon)
            return None

        width, height = int(bmp.bmWidth), int(bmp.bmHeight)
        if width <= 0 or height <= 0:
            gdi32.DeleteObject(iconinfo.hbmColor)
            gdi32.DeleteObject(iconinfo.hbmMask)
            user32.DestroyIcon(hicon)
            return None

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = width
        bi.biHeight = -height
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        hdc = user32.GetDC(None)
        gdi32.GetDIBits(hdc, iconinfo.hbmColor, 0, height, buf, ctypes.byref(bi), 0)
        user32.ReleaseDC(None, hdc)

        img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.DeleteObject(iconinfo.hbmColor)
        gdi32.DeleteObject(iconinfo.hbmMask)
        user32.DestroyIcon(hicon)
        return img
    except Exception:
        return None


def load_icon_image() -> Optional["Image.Image"]:
    if Image is None:
        return None
    p = ensure_icon_file() or find_app_icon_path()
    if p:
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            pass
    return _extract_icon_from_exe()
