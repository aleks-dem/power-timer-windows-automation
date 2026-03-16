from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable


class AbortDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        seconds: int,
        title: str,
        body: str,
        abort_event,
        on_hide: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.remaining = max(0, int(seconds))
        self.abort_event = abort_event
        self._on_hide = on_hide
        self._on_close = on_close
        self._closed = False

        self.title(title)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=body, justify="left").pack(anchor="w")

        self.counter_var = tk.StringVar(value=f"{self.remaining}s")
        ttk.Label(frm, textvariable=self.counter_var, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(10, 8))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(6, 0))

        ttk.Button(btns, text="Abort", command=self._abort).pack(side="left")
        ttk.Button(btns, text="Hide", command=self._hide).pack(side="left", padx=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._hide)

        self.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        self.after(1000, self._tick)

    def _abort(self):
        self.abort_event.set()
        try:
            self._cleanup()
        except Exception:
            pass

    def _hide(self):
        # keep countdown running but just hide window
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            if self._on_hide:
                self._on_hide()
        except Exception:
            pass
        self.withdraw()

    def _tick(self):
        if self.abort_event.is_set():
            try:
                self._cleanup()
            except Exception:
                pass
            return

        self.remaining -= 1
        if self.remaining <= 0:
            try:
                self._cleanup()
            except Exception:
                pass
            return

        self.counter_var.set(f"{self.remaining}s")
        self.after(1000, self._tick)

    def _cleanup(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            if self._on_close:
                self._on_close()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
