from __future__ import annotations

import ctypes
import datetime as dt
import queue
import shutil
import threading
from pathlib import Path
from typing import Optional, Tuple, Any

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

import psutil
from PIL import Image, ImageTk

from core.models import TaskConfig, ActiveTask, ACTIONS, TRIGGERS
from core.persistence import load_settings, save_ui_state, save_active_task, load_active_task
from core.scheduler import Scheduler, SchedulerTick, AbortCountdownRequest
from core.actions import clear_safeboot, is_admin, abort_shutdown
from core.task_scheduler import create_task, delete_task, task_exists, ScheduledTaskSpec
from core.verify_execution import verify_execution, get_scheduled_task_info, _parse_dt, _to_aware_local
from util.timefmt import format_hms
from util.logutil import setup_logging, list_log_files, read_tail_lines, clear_logs
from ui.dialogs import AbortDialog
from ui.tray import TrayManager, TrayState
from util.single_instance import (
    create_show_event,
    wait_for_show_event,
    close_handle,
    SHOW_EVENT_NAME,
)
from util.icon_data import ensure_icon_file, load_icon_image, set_window_icons
from util import paths


def app_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def settings_path() -> Path:
    p = paths.settings_path()
    if not p.exists():
        legacy = app_dir() / "settings.json"
        if legacy.exists():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, p)
            except Exception:
                pass
    return p


def log_path() -> Path:
    return paths.log_path()


def tmp_task_xml_dir() -> Path:
    return paths.tmp_task_xml_dir()


def parse_int(s: str, default: int = 0) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def parse_float(s: str, default: float = 0.0) -> float:
    try:
        return float(str(s).strip().replace(",", "."))
    except Exception:
        return default


def is_valid_hhmm(value: str) -> bool:
    try:
        hh, mm = value.strip().split(":")
        hh_i, mm_i = int(hh), int(mm)
    except Exception:
        return False
    return 0 <= hh_i <= 23 and 0 <= mm_i <= 59


def _deterministic_survive_exit_supported(cfg: TaskConfig) -> bool:
    # We only support survive-exit via Task Scheduler when next fire time is known now.
    return cfg.trigger in ("Countdown", "At time (HH:MM)")


class PowerTimerApp:
    def __init__(self) -> None:
        # Set AppUserModelID for taskbar grouping/icon behavior on Windows
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.powertimer.app")
        except Exception:
            pass  # harmless if not available

        self.root = tk.Tk()

        # Set Tk window icon (titlebar/top-left + often taskbar)
        self._icon_imgs: list[ImageTk.PhotoImage] = []
        ico = ensure_icon_file()
        if ico:
            try:
                # Use absolute path to avoid CWD issues in packaged apps/IDEs
                self.root.iconbitmap(default=str(ico))
            except Exception:
                pass
        try:
            self.root.update_idletasks()
            set_window_icons(self.root.winfo_id())
        except Exception:
            pass
        try:
            img = load_icon_image()
            if img:
                for size in (16, 24, 32, 48, 64, 128, 256):
                    resized = img.resize((size, size), Image.LANCZOS)
                    self._icon_imgs.append(ImageTk.PhotoImage(resized))
                if self._icon_imgs:
                    self.root.iconphoto(True, *self._icon_imgs)
        except Exception:
            pass
        
        self.root.title("PowerTimer")
        self.root.geometry("560x420")
        self.root.resizable(False, False)

        self.ui_q: "queue.Queue[Any]" = queue.Queue()

        # logging (file + push into UI)
        self.logger = setup_logging(
            log_path=log_path(),
            push_ui_line_cb=lambda line: self.ui_q.put(("log", line)),
        )

        # state
        self.active_task: Optional[ActiveTask] = None
        self._remaining: Optional[int] = None
        self._next_fire: Optional[dt.datetime] = None
        self._phase: str = "waiting"

        # tray
        self.tray = TrayManager(
            ui_call=lambda fn: self.root.after(0, fn),
            get_tray_state=self._get_tray_state,
            on_show=self.show_window,
            on_cancel=self.cancel_task,
            on_exit=self.exit_app,
            logger=self.logger
        )
        self.tray.start()

        # Show-window signal listener (for single-instance focus)
        self._show_event = create_show_event(SHOW_EVENT_NAME)
        if self._show_event:
            t = threading.Thread(
                target=wait_for_show_event,
                args=(self._show_event, lambda: self.root.after(0, self.show_window)),
                daemon=True,
            )
            t.start()

        # scheduler
        self.scheduler = Scheduler(
            logger=self.logger,
            on_tick=self._on_tick_from_worker,
            on_abort_request=self._on_abort_request_from_worker,
            on_active_task_update=self._on_active_task_update,
            on_done=self._on_done,
        )

        # UI vars
        self.action_var = tk.StringVar(value="Shutdown")
        self.force_close_var = tk.BooleanVar(value=True)
        self.block_fullscreen_var = tk.BooleanVar(value=True)
        self.survive_exit_var = tk.BooleanVar(value=False)

        self.trigger_var = tk.StringVar(value="Countdown")

        self.count_val = tk.StringVar(value="30")
        self.count_unit = tk.StringVar(value="minutes")

        now_plus_5 = dt.datetime.now().astimezone() + dt.timedelta(minutes=5)
        self.at_time_var = tk.StringVar(value=now_plus_5.strftime("%H:%M"))

        self.proc_filter_var = tk.StringVar(value="")
        self.proc_var = tk.StringVar(value="")
        self.proc_list: list[Tuple[str, int]] = []
        self.proc_delay_val = tk.StringVar(value="0")
        self.proc_delay_unit = tk.StringVar(value="seconds")

        self.cpu_thr_var = tk.StringVar(value="10")
        self.cpu_dur_var = tk.StringVar(value="120")

        self.disk_thr_var = tk.StringVar(value="200")
        self.disk_dur_var = tk.StringVar(value="120")

        self.idle_min_var = tk.StringVar(value="15")

        self.net_thr_var = tk.StringVar(value="30")
        self.net_dur_var = tk.StringVar(value="90")

        self._exiting = False
        self._abort_dialog: Optional[AbortDialog] = None

        # build UI
        self._build_ui()

        # load persisted UI + active task banner
        self._restore_from_settings()

        # close -> minimize to tray
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_to_tray)

        # poll UI queue
        self._poll_ui_queue()

    # ---------------- UI building ----------------

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        # Banner
        self.banner = ttk.Frame(self.root)
        self.banner.pack(fill="x", padx=10, pady=(8, 0))
        self.banner_label = ttk.Label(self.banner, text="", foreground="#0a0")
        self.banner_label.pack(side="left", fill="x", expand=True)
        self.banner_btn_cancel = ttk.Button(self.banner, text="Cancel", command=self.cancel_task)
        self.banner_btn_cancel.pack(side="right")
        self.banner.pack_forget()

        # Notebook
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, **pad)

        self.tab_main = ttk.Frame(self.nb)
        self.tab_log = ttk.Frame(self.nb)
        self.nb.add(self.tab_main, text="Main")
        self.nb.add(self.tab_log, text="Log")

        # Main top controls
        top = ttk.Frame(self.tab_main)
        top.pack(fill="x")

        ttk.Label(top, text="Action:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(top, textvariable=self.action_var, values=ACTIONS, state="readonly", width=28)\
            .grid(row=0, column=1, sticky="w", padx=(6, 0))

        ttk.Checkbutton(top, text="Force close apps (/f) for shutdown/restart", variable=self.force_close_var)\
            .grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Checkbutton(top, text="Do not execute while foreground is fullscreen", variable=self.block_fullscreen_var)\
            .grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Checkbutton(top, text="Survive exit (Task Scheduler)", variable=self.survive_exit_var, command=self._refresh_survive_exit_enabled)\
            .grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Label(top, text="Trigger:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        trig = ttk.Combobox(top, textvariable=self.trigger_var, values=TRIGGERS, state="readonly", width=28)
        trig.grid(row=4, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        trig.bind("<<ComboboxSelected>>", lambda _e: self._on_trigger_change())

        # Trigger frames
        self.frames = ttk.Frame(self.tab_main)
        self.frames.pack(fill="both", expand=True, pady=(8, 0))

        self.frame_map: dict[str, ttk.Frame] = {}
        self._make_frame_countdown()
        self._make_frame_at_time()
        self._make_frame_app_exit()
        self._make_frame_cpu_low()
        self._make_frame_disk_low()
        self._make_frame_idle()
        self._make_frame_net_idle()

        # Bottom buttons + status
        bottom = ttk.Frame(self.tab_main)
        bottom.pack(fill="x", pady=(6, 0))

        self.start_btn = ttk.Button(bottom, text="Start", command=self.start_task)
        self.start_btn.grid(row=0, column=0, sticky="w")
        self.cancel_btn = ttk.Button(bottom, text="Cancel task", command=self.cancel_task, state="disabled")
        self.cancel_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.safe_btn = ttk.Button(bottom, text="Clear SafeBoot flag (admin)", command=self.clear_safeboot_btn)
        self.safe_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.exit_btn = ttk.Button(bottom, text="Exit", command=self.exit_app_from_main)
        self.exit_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))

        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=0)
        bottom.columnconfigure(2, weight=0)
        bottom.columnconfigure(3, weight=0)

        self.status_var = tk.StringVar(value=f"Ready. {settings_path()}")
        ttk.Label(bottom, textvariable=self.status_var, wraplength=540).grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0)
        )

        # Log tab
        # Log tab
        self.verif_summary_var = tk.StringVar(value="Last verification summary: (none)")
        self.verif_lines_var = tk.StringVar(value="")

        verif = ttk.Labelframe(self.tab_log, text="Last verification summary")
        verif.pack(fill="x")

        ttk.Label(verif, textvariable=self.verif_summary_var).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Label(verif, textvariable=self.verif_lines_var, wraplength=540, foreground="#666")\
            .pack(anchor="w", padx=8, pady=(2, 6))

        self.btn_show_evidence = ttk.Button(verif, text="Show full evidence…", command=self.show_full_evidence)
        self.btn_show_evidence.pack(anchor="e", padx=8, pady=(0, 8))
        self.btn_show_evidence.configure(state="disabled")

        log_top = ttk.Frame(self.tab_log)
        log_top.pack(fill="x", pady=(8, 0))

        ttk.Button(log_top, text="Reload logs", command=self.reload_logs).pack(side="left")
        ttk.Button(log_top, text="Clear logs", command=self.clear_logs_btn).pack(side="left", padx=(8, 0))

        self.log_text = ScrolledText(self.tab_log, height=12)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text.configure(state="disabled")

        self._show_trigger_frame()
        self._refresh_processes()
        self._apply_proc_filter()

        # autosave UI
        self._setup_autosave()

    def _make_frame_countdown(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["Countdown"] = f

        ttk.Label(f, text="Countdown:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.count_val, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Combobox(f, textvariable=self.count_unit, values=("seconds", "minutes", "hours"), state="readonly", width=10)\
            .grid(row=0, column=2, sticky="w", padx=(6, 0))

        presets = ttk.Frame(f)
        presets.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        for i, (txt, v, u) in enumerate([("15 min", 15, "minutes"), ("30 min", 30, "minutes"), ("1 hour", 1, "hours")]):
            ttk.Button(presets, text=txt, width=10, command=lambda v=v, u=u: (self.count_val.set(str(v)), self.count_unit.set(u)))\
                .grid(row=0, column=i, padx=(0 if i == 0 else 6, 0))

    def _make_frame_at_time(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["At time (HH:MM)"] = f

        ttk.Label(f, text="Run at (24h HH:MM):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.at_time_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(f, text="If time already passed today, it will run tomorrow.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _make_frame_app_exit(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["After app exits"] = f

        ttk.Label(f, text="Process filter:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.proc_filter_var, width=28).grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.proc_filter_var.trace_add("write", lambda *_: self._apply_proc_filter())

        ttk.Label(f, text="Select process (PID):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.proc_combo = ttk.Combobox(f, textvariable=self.proc_var, values=[], state="readonly", width=40)
        self.proc_combo.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk.Button(f, text="Refresh", command=self._refresh_processes).grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(8, 0))

        ttk.Label(f, text="Delay after exit:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.proc_delay_val, width=10).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk.Combobox(f, textvariable=self.proc_delay_unit, values=("seconds", "minutes"), state="readonly", width=10)\
            .grid(row=2, column=2, sticky="w", padx=(6, 0), pady=(8, 0))

        ttk.Label(f, text="Note: 'Survive exit' is not supported here (exit moment is unknown until it happens).").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )

    def _make_frame_cpu_low(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["CPU low for N seconds"] = f
        ttk.Label(f, text="CPU <= threshold (%):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.cpu_thr_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(f, text="For how long (seconds):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.cpu_dur_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))

    def _make_frame_disk_low(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["Disk low for N seconds"] = f
        ttk.Label(f, text="Disk <= (KB/s):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.disk_thr_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(f, text="For how long (seconds):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.disk_dur_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))

    def _make_frame_idle(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["User idle for N minutes"] = f
        ttk.Label(f, text="Idle minutes:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.idle_min_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))

    def _make_frame_net_idle(self) -> None:
        f = ttk.Frame(self.frames)
        self.frame_map["Network idle for N seconds"] = f
        ttk.Label(f, text="Network <= (KB/s):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.net_thr_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(f, text="For how long (seconds):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.net_dur_var, width=10).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))

    def _clear_frames(self) -> None:
        for f in self.frame_map.values():
            f.pack_forget()

    def _show_trigger_frame(self) -> None:
        self._clear_frames()
        t = self.trigger_var.get()
        frame = self.frame_map.get(t)
        if frame:
            frame.pack(fill="both", expand=True)

    def _on_trigger_change(self) -> None:
        self._show_trigger_frame()
        self._refresh_survive_exit_enabled()

    def _refresh_survive_exit_enabled(self) -> None:
        cfg = self._build_config()
        supported = _deterministic_survive_exit_supported(cfg)
        # If unsupported, force checkbox off
        if not supported:
            self.survive_exit_var.set(False)

    # ---------------- tray behavior ----------------

    def on_close_to_tray(self) -> None:
        self.hide_to_tray()

    def hide_to_tray(self) -> None:
        self.root.withdraw()
        self.logger.info("Window hidden to tray.")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_app_from_main(self) -> None:
        if not messagebox.askyesno(
            "Exit",
            "Are you sure? Tasks without Survive Exit will be reset.",
        ):
            return
        self.exit_app(confirm=False)

    def exit_app(self, confirm: bool = False) -> None:
        if confirm:
            if not messagebox.askyesno(
                "Exit",
                "Are you sure? Tasks without Survive Exit will be reset.",
            ):
                return
        keep_scheduled = False
        cfg = TaskConfig.from_dict(self.active_task.config) if self.active_task else None
        if self.active_task and self.active_task.status == "active" and cfg:
            keep_scheduled = bool(cfg.survive_exit and self.active_task.scheduled_task_name)

        # Explicit exit: warn if task would be canceled and not survive-exit
        if self.scheduler.running() and (not keep_scheduled):
            if cfg and not cfg.survive_exit:
                if not messagebox.askyesno("Exit", "A task is running. Exiting will cancel it. Exit anyway?"):
                    return

        self._exiting = True

        if not keep_scheduled:
            try:
                self.cancel_task(silent=True)
            except Exception:
                pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            close_handle(self._show_event)
            self._show_event = None
        except Exception:
            pass
        self.root.destroy()

    # ---------------- persistence ----------------

    def _restore_from_settings(self) -> None:
        s = load_settings(settings_path())
        ui = s.ui or {}
        # restore UI vars
        def set_if(k, setter):
            if k in ui:
                try:
                    setter(ui[k])
                except Exception:
                    pass

        set_if("action", self.action_var.set)
        set_if("force_close", lambda v: self.force_close_var.set(bool(v)))
        set_if("block_fullscreen", lambda v: self.block_fullscreen_var.set(bool(v)))
        set_if("survive_exit", lambda v: self.survive_exit_var.set(bool(v)))

        set_if("trigger", self.trigger_var.set)
        set_if("count_val", self.count_val.set)
        set_if("count_unit", self.count_unit.set)
        set_if("at_time", self.at_time_var.set)
        set_if("proc_filter", self.proc_filter_var.set)
        set_if("proc_sel", self.proc_var.set)
        set_if("proc_delay_val", self.proc_delay_val.set)
        set_if("proc_delay_unit", self.proc_delay_unit.set)

        set_if("cpu_thr", self.cpu_thr_var.set)
        set_if("cpu_dur", self.cpu_dur_var.set)
        set_if("disk_thr", self.disk_thr_var.set)
        set_if("disk_dur", self.disk_dur_var.set)
        set_if("idle_min", self.idle_min_var.set)
        set_if("net_thr", self.net_thr_var.set)
        set_if("net_dur", self.net_dur_var.set)

        self._show_trigger_frame()
        self._refresh_processes()
        self._apply_proc_filter()
        self._refresh_survive_exit_enabled()

        # restore active task banner
        self.active_task = load_active_task(settings_path())
        self._refresh_banner()
        
        self._refresh_verification_summary()
                
        # Post-reboot / post-exit verification (Event Log + Task Scheduler)
        self._verify_previous_task_if_needed()

        # load logs into UI
        self.reload_logs()

        # If active task exists and is still pending and not running, try to resume deterministic countdown in-app
        self._maybe_resume_active_task()

    def _maybe_resume_active_task(self) -> None:
        if not self.active_task:
            return
        if self.scheduler.running():
            return
        if self.active_task.status != "active":
            return
        if self.active_task.scheduled_task_name:
            # Survive-exit task is handled by Task Scheduler; don't restart in-app countdown.
            return
        cfg = TaskConfig.from_dict(self.active_task.config)
        # Resume only if deterministic and fire_time in future
        if cfg.trigger in ("Countdown", "At time (HH:MM)", "After app exits"):
            nft = self.active_task.next_fire_time_iso
            if nft:
                try:
                    fire_at = dt.datetime.fromisoformat(nft)
                    if fire_at > dt.datetime.now().astimezone():
                        self.logger.info("Resuming active task in-app (banner).")
                        self.start_btn.configure(state="disabled")
                        self.cancel_btn.configure(state="normal")
                        self.scheduler.start(self.active_task)
                except Exception:
                    pass

    def _verify_previous_task_if_needed(self) -> None:
        if not self.active_task:
            return

        t = self.active_task
        if t.status != "active":
            return

        # If task was scheduled (survive-exit) or has expected time already in the past and app isn't running it,
        # try to verify and update state.
        now = dt.datetime.now().astimezone()
        nft = None
        if t.next_fire_time_iso:
            try:
                nft = dt.datetime.fromisoformat(t.next_fire_time_iso.replace("Z", "+00:00")).astimezone()
            except Exception:
                nft = None

        # If we have a scheduled task, consult Task Scheduler for next run time to avoid
        # prematurely verifying/cleaning tasks that are still in the future.
        if t.scheduled_task_name:
            info = get_scheduled_task_info(t.scheduled_task_name)
            if info:
                nrt = info.get("NextRunTime")
                nrt_dt = _parse_dt(nrt) if isinstance(nrt, str) else None
                if nrt_dt:
                    nrt_dt = _to_aware_local(nrt_dt)
                    t.next_fire_time_iso = nrt_dt.isoformat(timespec="seconds")
                    save_active_task(settings_path(), t)
                    if nrt_dt > (now + dt.timedelta(seconds=30)):
                        self._refresh_banner()
                        return

        should_check = bool(t.scheduled_task_name) or (nft is not None and nft < (now - dt.timedelta(seconds=30)))
        if not should_check:
            return

        # If survive-exit task is scheduled in the future, don't verify/cleanup.
        if t.scheduled_task_name and nft is not None and nft > (now + dt.timedelta(seconds=30)):
            return

        # If task time is in the past and no scheduler task exists, mark stale immediately.
        if nft is not None and nft < (now - dt.timedelta(seconds=30)) and not t.scheduled_task_name:
            t.status = "stale"
            t.note = (t.note + " | " if t.note else "") + "Expired: time is in the past"
            save_active_task(settings_path(), t)
            self._refresh_banner()
            self._refresh_verification_summary()
            return

        self.logger.info("Verifying previous task execution via Task Scheduler + Event Log...")
        res = verify_execution(self.logger, t)

        t.verified_status = res.status
        t.verified_details = res.details

        # Update status heuristically:
        if res.status in ("yes", "likely"):
            t.status = "completed"
            t.note = (t.note + " | " if t.note else "") + f"Verified: {res.status}"
        elif res.status == "no":
            t.status = "stale"
            t.note = (t.note + " | " if t.note else "") + "Verified: no evidence (missed/failed)"
        else:
            t.note = (t.note + " | " if t.note else "") + "Verified: unknown"
            if nft is not None and nft < (now - dt.timedelta(minutes=5)):
                if t.scheduled_task_name and not task_exists(t.scheduled_task_name):
                    t.status = "stale"
                    t.note = (t.note + " | " if t.note else "") + "Task no longer active"

        save_active_task(settings_path(), t)
        self._refresh_banner()
        
        self._refresh_verification_summary()

        # Log details
        self.logger.info("Verification result: %s", res.status)
        for line in res.details:
            self.logger.info("  %s", line)

        # Cleanup scheduled task only when we have a definitive outcome.
        if t.scheduled_task_name and res.status in ("yes", "likely", "no"):
            try:
                delete_task(t.scheduled_task_name)
                self.logger.info("Scheduled task cleaned up: %s", t.scheduled_task_name)
            except Exception:
                pass    
    
    def _save_ui(self) -> None:
        ui = {
            "action": self.action_var.get(),
            "force_close": bool(self.force_close_var.get()),
            "block_fullscreen": bool(self.block_fullscreen_var.get()),
            "survive_exit": bool(self.survive_exit_var.get()),
            "trigger": self.trigger_var.get(),
            "count_val": self.count_val.get(),
            "count_unit": self.count_unit.get(),
            "at_time": self.at_time_var.get(),
            "proc_filter": self.proc_filter_var.get(),
            "proc_sel": self.proc_var.get(),
            "proc_delay_val": self.proc_delay_val.get(),
            "proc_delay_unit": self.proc_delay_unit.get(),
            "cpu_thr": self.cpu_thr_var.get(),
            "cpu_dur": self.cpu_dur_var.get(),
            "disk_thr": self.disk_thr_var.get(),
            "disk_dur": self.disk_dur_var.get(),
            "idle_min": self.idle_min_var.get(),
            "net_thr": self.net_thr_var.get(),
            "net_dur": self.net_dur_var.get(),
        }
        save_ui_state(settings_path(), ui)

    def _setup_autosave(self) -> None:
        # debounce autosave
        self._save_after_id: Optional[str] = None

        def schedule_save(*_):
            if self._save_after_id:
                try:
                    self.root.after_cancel(self._save_after_id)
                except Exception:
                    pass
            self._save_after_id = self.root.after(600, self._save_ui)

        for v in [
            self.action_var, self.force_close_var, self.block_fullscreen_var, self.survive_exit_var,
            self.trigger_var,
            self.count_val, self.count_unit,
            self.at_time_var,
            self.proc_filter_var, self.proc_var, self.proc_delay_val, self.proc_delay_unit,
            self.cpu_thr_var, self.cpu_dur_var,
            self.disk_thr_var, self.disk_dur_var,
            self.idle_min_var,
            self.net_thr_var, self.net_dur_var
        ]:
            try:
                v.trace_add("write", schedule_save)
            except Exception:
                pass

    # ---------------- process list + filter ----------------

    def _refresh_processes(self) -> None:
        items: list[Tuple[str, int]] = []
        for p in psutil.process_iter(attrs=["pid", "name"]):
            try:
                pid = int(p.info["pid"])
                name = p.info.get("name") or "unknown.exe"
                items.append((f"{name} (PID {pid})", pid))
            except Exception:
                continue
        items.sort(key=lambda x: x[0].lower())
        self.proc_list = items
        self._apply_proc_filter()

    def _apply_proc_filter(self) -> None:
        needle = (self.proc_filter_var.get() or "").strip().lower()
        filtered = [disp for (disp, _pid) in self.proc_list if needle in disp.lower()]
        if hasattr(self, "proc_combo"):
            self.proc_combo["values"] = filtered
        if filtered and (self.proc_var.get() not in filtered):
            self.proc_var.set(filtered[0])

    # ---------------- build config ----------------

    def _build_config(self) -> TaskConfig:
        cfg = TaskConfig(
            action=self.action_var.get(),
            force_close_apps=bool(self.force_close_var.get()),
            block_fullscreen=bool(self.block_fullscreen_var.get()),
            survive_exit=bool(self.survive_exit_var.get()),
            trigger=self.trigger_var.get(),
        )

        if cfg.trigger == "Countdown":
            val = parse_int(self.count_val.get(), 0)
            unit = self.count_unit.get()
            mult = {"seconds": 1, "minutes": 60, "hours": 3600}.get(unit, 60)
            cfg.seconds = max(0, val * mult)

        elif cfg.trigger == "At time (HH:MM)":
            cfg.at_hhmm = self.at_time_var.get()

        elif cfg.trigger == "After app exits":
            sel = self.proc_var.get()
            pid = None
            for disp, p in self.proc_list:
                if disp == sel:
                    pid = p
                    break
            cfg.target_pid = pid

            dv = parse_int(self.proc_delay_val.get(), 0)
            du = self.proc_delay_unit.get()
            cfg.process_delay_seconds = dv * (60 if du == "minutes" else 1)

        elif cfg.trigger == "CPU low for N seconds":
            cfg.cpu_threshold = parse_float(self.cpu_thr_var.get(), 10.0)
            cfg.cpu_duration_s = parse_int(self.cpu_dur_var.get(), 60)

        elif cfg.trigger == "Disk low for N seconds":
            cfg.disk_kbps_threshold = parse_float(self.disk_thr_var.get(), 200.0)
            cfg.disk_duration_s = parse_int(self.disk_dur_var.get(), 60)

        elif cfg.trigger == "User idle for N minutes":
            cfg.idle_minutes = parse_int(self.idle_min_var.get(), 10)

        elif cfg.trigger == "Network idle for N seconds":
            cfg.net_kbps_threshold = parse_float(self.net_thr_var.get(), 20.0)
            cfg.net_duration_s = parse_int(self.net_dur_var.get(), 60)

        return cfg

    # ---------------- start/cancel ----------------

    def start_task(self) -> None:
        if self.scheduler.running():
            messagebox.showinfo("Already running", "A task is already running.")
            return

        cfg = self._build_config()

        if cfg.trigger == "At time (HH:MM)" and not is_valid_hhmm(cfg.at_hhmm):
            messagebox.showerror("Invalid time", "Please enter time in HH:MM format (24h), e.g. 23:45.")
            return

        if cfg.trigger == "After app exits" and not cfg.target_pid:
            messagebox.showerror("Process required", "Select a process for the 'After app exits' trigger.")
            return
        
        # Survive-exit: allow "After app exits" ONLY if the process already exited now,
        # then it degenerates into a pure delay countdown.
        if cfg.survive_exit and cfg.trigger == "After app exits":
            if cfg.target_pid and (not psutil.pid_exists(cfg.target_pid)):
                self.logger.info("Process already exited; converting trigger to Countdown(delay) for survive-exit.")
                cfg.trigger = "Countdown"
                cfg.seconds = max(0, cfg.process_delay_seconds)
                # reflect in active task config later
            else:
                cfg.survive_exit = False
                self.survive_exit_var.set(False)
                self.logger.warning("Survive exit disabled: process-exit trigger is not deterministic until exit happens.")

        # Validate survive_exit capability (Countdown/At time are deterministic)
        if cfg.survive_exit and not _deterministic_survive_exit_supported(cfg):
            cfg.survive_exit = False
            self.survive_exit_var.set(False)
            self.logger.warning("Survive exit disabled: trigger is not deterministic (%s).", cfg.trigger)

        # Safe mode requires admin (because bcdedit)
        if cfg.action.startswith("Restart (Safe Mode") and not is_admin():
            messagebox.showerror("Admin required", "Safe Mode restart requires Administrator privileges (bcdedit).")
            return

        # Create active task object
        self.active_task = ActiveTask.new(cfg)
        save_active_task(settings_path(), self.active_task)

        # If survive_exit enabled: create a scheduled task (Countdown / At-time only)
        if cfg.survive_exit:
            try:
                fire_at = self._compute_fire_at_for_survive_exit(cfg)
                cmd = self._scheduled_command_for_action(cfg)
                task_name = f"PowerTimer_{self.active_task.task_id}"

                # SafeMode tasks should run elevated; use SYSTEM principal when needed
                use_interactive = not cfg.action.startswith("Restart (Safe Mode")
                spec = ScheduledTaskSpec(
                    name=task_name,
                    run_at=fire_at,
                    command=cmd,
                    runlevel_highest=cfg.action.startswith("Restart (Safe Mode"),
                    use_interactive_token=use_interactive
                )
                create_task(spec, tmp_task_xml_dir())

                self.active_task.scheduled_task_name = task_name
                self.active_task.next_fire_time_iso = fire_at.isoformat(timespec="seconds")
                save_active_task(settings_path(), self.active_task)

                self.logger.info("Scheduled task created: %s at %s", task_name, fire_at.isoformat(timespec="seconds"))
            except Exception as e:
                self.logger.exception("Failed to create scheduled task: %r", e)
                messagebox.showerror("Task Scheduler error", str(e))
                self.active_task.status = "stale"
                self.active_task.note = f"Failed to schedule: {e!r}"
                save_active_task(settings_path(), self.active_task)
                self._refresh_banner()
                return

        self._refresh_banner()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.logger.info("Starting in-app scheduler.")
        self.scheduler.start(self.active_task)

    def _compute_fire_at_for_survive_exit(self, cfg: TaskConfig) -> dt.datetime:
        if cfg.trigger == "Countdown":
            return dt.datetime.now().astimezone() + dt.timedelta(seconds=max(0, cfg.seconds))
        if cfg.trigger == "At time (HH:MM)":
            hh, mm = cfg.at_hhmm.strip().split(":")
            hh_i, mm_i = int(hh), int(mm)
            now = dt.datetime.now().astimezone()
            t = now.replace(hour=hh_i, minute=mm_i, second=0, microsecond=0)
            if t <= now:
                t += dt.timedelta(days=1)
            return t
        raise ValueError("Survive exit supported only for Countdown and At time")

    def _scheduled_command_for_action(self, cfg: TaskConfig) -> str:
        # Command will be run as: cmd.exe /c <this string>
        a = cfg.action
        if a == "Shutdown":
            return f"shutdown /s /t 0 {'/f' if cfg.force_close_apps else ''}".strip()
        if a == "Restart":
            return f"shutdown /r /t 0 {'/f' if cfg.force_close_apps else ''}".strip()
        if a == "Hibernate":
            return "shutdown /h"
        if a == "Lock":
            return r"rundll32.exe user32.dll,LockWorkStation"
        if a == "Sleep":
            # Common approach; no perfect official CLI equivalent.
            return r"rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
        if a == "Restart (Safe Mode minimal)":
            return r"bcdedit /set {current} safeboot minimal & shutdown /r /t 0"
        if a == "Restart (Safe Mode + Networking)":
            return r"bcdedit /set {current} safeboot network & shutdown /r /t 0"
        raise ValueError(f"Unsupported action for Task Scheduler: {a}")

    def cancel_task(self, silent: bool = False) -> None:
        if not self.active_task and not self.scheduler.running():
            if not silent:
                messagebox.showinfo("No task", "No active task.")
            return

        # Stop in-app
        if self.scheduler.running():
            self.scheduler.stop()

        # Cancel pending shutdown just in case
        abort_shutdown()

        # Delete scheduled task if any
        if self.active_task and self.active_task.scheduled_task_name:
            try:
                delete_task(self.active_task.scheduled_task_name)
                self.logger.info("Scheduled task deleted: %s", self.active_task.scheduled_task_name)
            except Exception:
                pass

        if self.active_task:
            self.active_task.status = "canceled"
            self.active_task.note = "Canceled by user"
            save_active_task(settings_path(), self.active_task)

        self._refresh_banner()
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status_var.set("Task cancelled.")

    # ---------------- banner + tray state ----------------

    def _refresh_banner(self) -> None:
        if not self.active_task or self.active_task.status != "active":
            self.banner.pack_forget()
            self.start_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            return

        cfg = TaskConfig.from_dict(self.active_task.config)
        nft = self.active_task.next_fire_time_iso
        txt = f"Active task: {cfg.action} / {cfg.trigger}"
        if nft:
            txt += f" | at {nft}"
        if cfg.survive_exit and self.active_task.scheduled_task_name:
            txt += f" | survive-exit ON ({self.active_task.scheduled_task_name})"
        self.banner_label.configure(text=txt)
        self.banner.pack(fill="x", padx=10, pady=(8, 0))
        # When an active task exists, disable start and enable cancel.
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

    def _get_tray_state(self) -> TrayState:
        active = bool(self.active_task and self.active_task.status == "active")
        blink = active
        tooltip = "PowerTimer"
        if active:
            cfg = TaskConfig.from_dict(self.active_task.config)
            if self._remaining is not None and self._next_fire is not None:
                tooltip = f"{cfg.action}: {format_hms(self._remaining)} remaining"
            elif self.active_task.next_fire_time_iso:
                tooltip = f"{cfg.action} at {self.active_task.next_fire_time_iso}"
            else:
                tooltip = f"{cfg.action}: waiting ({cfg.trigger})"
        return TrayState(active=active, tooltip=tooltip, blink=blink)

    # ---------------- log tab ----------------

    def reload_logs(self) -> None:
        lf = list_log_files(log_path())
        # oldest -> newest: .N ... .1 then current
        paths = list(reversed(lf.backups)) + [lf.current]
        lines = read_tail_lines(paths, max_lines=3000)

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(lines) + ("\n" if lines else ""))
        self.log_text.configure(state="disabled")
        self.log_text.yview_moveto(1.0)

    def clear_logs_btn(self) -> None:
        if not messagebox.askyesno("Clear logs", "Delete log files (powertimer.log, .1, .2...)?"):
            return
        clear_logs(log_path())
        self.reload_logs()
        self.logger.info("Logs cleared by user.")
        
    def _refresh_verification_summary(self) -> None:
        t = self.active_task
        verified_status = getattr(t, "verified_status", None) if t else None
        verified_details = getattr(t, "verified_details", None) if t else None

        if not t or not verified_status:
            self.verif_summary_var.set("Last verification summary: (none)")
            self.verif_lines_var.set("")
            if hasattr(self, "btn_show_evidence"):
                self.btn_show_evidence.configure(state="disabled")
            return

        self.verif_summary_var.set(f"Last verification summary: {verified_status}")

        lines = (verified_details or [])[:2]
        self.verif_lines_var.set("\n".join(lines) if lines else "(no evidence lines)")

        if hasattr(self, "btn_show_evidence"):
            self.btn_show_evidence.configure(
                state="normal" if (verified_details and len(verified_details) > 0) else "disabled"
            )

    def show_full_evidence(self) -> None:
        t = self.active_task
        lines = (t.verified_details or []) if t else []
        if not lines:
            messagebox.showinfo("Evidence", "No verification evidence stored.")
            return

        win = tk.Toplevel(self.root)
        win.title("Verification evidence")
        win.geometry("720x420")
        win.resizable(True, True)

        txt = ScrolledText(win)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("end", "\n".join(lines))
        txt.configure(state="disabled")
        txt.yview_moveto(0.0)

    # ---------------- scheduler callbacks ----------------

    def _on_tick_from_worker(self, tick: SchedulerTick) -> None:
        # Avoid overwriting status text after cancel.
        if self.active_task and self.active_task.status == "canceled":
            return
        self.ui_q.put(("tick", tick))

    def _on_abort_request_from_worker(self, req: AbortCountdownRequest) -> None:
        self.ui_q.put(("abort", req))

    def _on_active_task_update(self, task: ActiveTask) -> None:
        self.active_task = task
        save_active_task(settings_path(), task)
        self.ui_q.put(("banner", None))

    def _on_done(self) -> None:
        self.ui_q.put(("done", None))

        # if task completed/canceled and scheduled task exists, attempt cleanup
        if self.active_task and self.active_task.scheduled_task_name:
            cfg = None
            try:
                cfg = TaskConfig.from_dict(self.active_task.config)
            except Exception:
                cfg = None
            if not (self._exiting and cfg and cfg.survive_exit):
                try:
                    delete_task(self.active_task.scheduled_task_name)
                except Exception:
                    pass

    # ---------------- UI queue loop ----------------

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                if kind == "tick":
                    tick: SchedulerTick = payload
                    self.status_var.set(tick.text)

                    self._phase = tick.phase
                    self._remaining = tick.remaining_seconds
                    if tick.next_fire_time:
                        try:
                            self._next_fire = dt.datetime.fromisoformat(tick.next_fire_time)
                        except Exception:
                            self._next_fire = None

                elif kind == "abort":
                    req: AbortCountdownRequest = payload
                    if self._abort_dialog:
                        try:
                            self._abort_dialog._cleanup()
                        except Exception:
                            pass
                    dlg = AbortDialog(
                        self.root,
                        req.seconds,
                        req.title,
                        req.body,
                        req.abort_event,
                        on_hide=self._on_abort_dialog_hide,
                        on_close=self._on_abort_dialog_close,
                    )
                    self._abort_dialog = dlg
                    dlg.grab_set()

                elif kind == "banner":
                    self._refresh_banner()
                    self._refresh_verification_summary()

                elif kind == "done":
                    # finalize UI state
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self._refresh_banner()
                    if self.active_task and self.active_task.status == "canceled":
                        self.status_var.set("Task cancelled.")

                elif kind == "log":
                    line = payload
                    # append to log tab
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", line + "\n")
                    self.log_text.configure(state="disabled")
                    self.log_text.yview_moveto(1.0)

        except queue.Empty:
            pass

        self.root.after(200, self._poll_ui_queue)

    def _on_abort_dialog_hide(self) -> None:
        self.status_var.set("Abort countdown running (hidden). Cancel task if needed.")

    def _on_abort_dialog_close(self) -> None:
        self._abort_dialog = None

    # ---------------- other buttons ----------------

    def clear_safeboot_btn(self) -> None:
        try:
            cleared = clear_safeboot()
            if cleared:
                messagebox.showinfo("OK", "SafeBoot flag cleared.\nWindows will boot normally after next restart.")
                self.logger.info("SafeBoot flag cleared.")
            else:
                messagebox.showinfo("OK", "SafeBoot flag was not set.\nWindows will boot normally.")
                self.logger.info("SafeBoot flag not set; nothing to clear.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.logger.exception("SafeBoot clear failed: %r", e)

    # ---------------- run ----------------

    def run(self) -> None:
        self.root.mainloop()
