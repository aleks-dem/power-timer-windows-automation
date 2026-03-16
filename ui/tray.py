from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw

from util.icon_data import load_icon_image

def _make_icon(size: int = 64, variant: int = 0) -> Image.Image:
    """
    Simple "clock + power" style icon generated in code (no external ico needed).
    variant toggles for blinking.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background circle
    if variant == 0:
        bg = (30, 30, 30, 255)
        fg = (235, 235, 235, 255)
        accent = (80, 180, 255, 255)
    else:
        bg = (80, 180, 255, 255)
        fg = (10, 10, 10, 255)
        accent = (255, 220, 80, 255)

    d.ellipse((4, 4, size - 4, size - 4), fill=bg)

    # Clock face
    d.ellipse((12, 12, size - 12, size - 12), outline=fg, width=3)
    # Hands
    cx, cy = size // 2, size // 2
    d.line((cx, cy, cx, 18), fill=fg, width=3)
    d.line((cx, cy, size - 18, cy + 8), fill=accent, width=3)

    # Power symbol (small)
    d.arc((16, 16, 32, 32), start=40, end=320, fill=accent, width=3)
    d.line((24, 14, 24, 22), fill=accent, width=3)

    return img


@dataclass
class TrayState:
    active: bool = False
    tooltip: str = "PowerTimer"
    blink: bool = False


class TrayManager:
    def __init__(
        self,
        ui_call: Callable[[Callable[[], None]], None],   # run function in UI thread
        get_tray_state: Callable[[], TrayState],
        on_show: Callable[[], None],
        on_cancel: Callable[[], None],
        on_exit: Callable[[], None],
        logger=None
    ) -> None:
        self.ui_call = ui_call
        self.get_state = get_tray_state
        self.on_show = on_show
        self.on_cancel = on_cancel
        self.on_exit = on_exit
        self.log = logger

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        img = load_icon_image()
        if img:
            try:
                if img.size != (64, 64):
                    img = img.resize((64, 64), Image.LANCZOS)
                self._img0 = img
                blink = img.copy()
                d = ImageDraw.Draw(blink)
                d.ellipse((46, 46, 62, 62), fill=(80, 255, 120, 255))
                d.ellipse((48, 48, 60, 60), outline=(0, 0, 0, 200), width=1)
                self._img1 = blink
            except Exception:
                self._img0 = _make_icon(64, 0)
                self._img1 = _make_icon(64, 1)
        else:
            self._img0 = _make_icon(64, 0)
            self._img1 = _make_icon(64, 1)

        self.icon = pystray.Icon(
            "PowerTimer",
            icon=self._img0,
            title="PowerTimer",
            menu=pystray.Menu(
                Item("Show", lambda: self.ui_call(self.on_show), default=True),
                Item("Cancel task", lambda: self.ui_call(self.on_cancel)),
                Item("Exit", lambda: self.ui_call(self.on_exit)),
            ),
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.icon.stop()
        except Exception:
            pass

    def _run(self) -> None:
        # Run icon in a separate thread from the Tk UI thread.
        t = threading.Thread(target=self.icon.run, daemon=True)
        t.start()

        blink_on = False
        while not self._stop.is_set():
            st = self.get_state()
            try:
                self.icon.title = st.tooltip
            except Exception:
                pass

            if st.active and st.blink:
                blink_on = not blink_on
                self.icon.icon = self._img1 if blink_on else self._img0
            else:
                self.icon.icon = self._img0

            self._stop.wait(timeout=0.6)

        try:
            self.icon.stop()
        except Exception:
            pass
