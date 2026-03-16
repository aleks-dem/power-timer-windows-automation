from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable

from core.models import TaskConfig, ActiveTask
from core import triggers
from core.actions import execute_action
from win.fullscreen import foreground_is_fullscreen
from util.timefmt import format_hms


# UI event types (kept simple: pass callables/events)
@dataclass
class AbortCountdownRequest:
    seconds: int
    title: str
    body: str
    abort_event: threading.Event


@dataclass
class SchedulerTick:
    text: str
    remaining_seconds: Optional[int] = None
    next_fire_time: Optional[str] = None
    phase: str = "waiting"


class Scheduler:
    """
    Runs a single active task in a background thread.
    Communicates via callbacks:
      - on_tick(SchedulerTick)
      - on_abort_request(AbortCountdownRequest)
      - on_done()
    """
    def __init__(
        self,
        logger,
        on_tick: Callable[[SchedulerTick], None],
        on_abort_request: Callable[[AbortCountdownRequest], None],
        on_active_task_update: Callable[[ActiveTask], None],
        on_done: Callable[[], None],
    ) -> None:
        self.log = logger
        self.on_tick = on_tick
        self.on_abort_request = on_abort_request
        self.on_active_task_update = on_active_task_update
        self.on_done = on_done

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.active: Optional[ActiveTask] = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()

    def start(self, active_task: ActiveTask) -> None:
        if self.running():
            raise RuntimeError("Task already running")
        self.active = active_task
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---------- internal ----------

    def _update_active(self, **kwargs) -> None:
        if not self.active:
            return
        for k, v in kwargs.items():
            if hasattr(self.active, k):
                setattr(self.active, k, v)
        self.on_active_task_update(self.active)

    def _set_fire_time(self, fire_at: dt.datetime) -> None:
        self._update_active(next_fire_time_iso=fire_at.isoformat(timespec="seconds"))

    def _wait_until_fire_time(self, cfg: TaskConfig, fire_at: dt.datetime) -> bool:
        """
        Returns True if should execute, False if aborted/canceled.
        Abort countdown is integrated: shown only when remaining <= 30, without adding time.
        """
        abort_shown = False
        abort_event = threading.Event()
        fired = False

        while not self._stop.is_set():
            now = dt.datetime.now().astimezone()

            remaining = int((fire_at - now).total_seconds())
            if remaining <= 0:
                fired = True
                break

            # human timer tick
            self._update_active(remaining_seconds=remaining, phase="counting")
            self.on_tick(SchedulerTick(
                text=f"Next action in {format_hms(remaining)} (at {fire_at.strftime('%Y-%m-%d %H:%M:%S')})",
                remaining_seconds=remaining,
                next_fire_time=fire_at.isoformat(timespec="seconds"),
                phase="counting"
            ))

            # Abort dialog appears when remaining <= 30 (or immediately if <=30 at start)
            if remaining <= 30 and not abort_shown:
                abort_shown = True
                self.log.info("Arming abort countdown (%ds)", remaining)
                self.on_abort_request(AbortCountdownRequest(
                    seconds=remaining,
                    title="About to execute",
                    body=f"Action: {cfg.action}\nAbort within {remaining} seconds.",
                    abort_event=abort_event
                ))
                self._update_active(phase="armed")

            if abort_event.is_set():
                self.log.info("Aborted by user during final countdown.")
                self._update_active(status="canceled", phase="waiting", note="Aborted in final countdown")
                return False

            # Wait 1 second for stable ticking
            self._stop.wait(timeout=1.0)

        if self._stop.is_set():
            self._update_active(status="canceled", note="Canceled by user")
            return False
        return fired

    def _fullscreen_block_if_needed(self, cfg: TaskConfig) -> bool:
        if not cfg.block_fullscreen:
            return True
        fs, desc = foreground_is_fullscreen()
        if not fs:
            return True

        self.log.info("Fullscreen detected; blocking action: %s", desc)
        while not self._stop.is_set():
            fs2, desc2 = foreground_is_fullscreen()
            if not fs2:
                self.log.info("Fullscreen cleared; proceeding.")
                return True
            self.on_tick(SchedulerTick(text=f"Fullscreen detected, waiting: {desc2}", phase="waiting"))
            self._stop.wait(timeout=1.0)
        return False

    def _run(self) -> None:
        assert self.active is not None
        try:
            cfg = TaskConfig.from_dict(self.active.config)
            self.log.info("Task started: trigger=%s action=%s", cfg.trigger, cfg.action)

            fire_at: Optional[dt.datetime] = None
            self._update_active(phase="waiting")

            # -------- resolve trigger to a fire time --------
            if cfg.trigger == "Countdown":
                if self.active and self.active.next_fire_time_iso:
                    try:
                        fire_at = dt.datetime.fromisoformat(self.active.next_fire_time_iso).astimezone()
                    except Exception:
                        fire_at = None
                if not fire_at:
                    fire_at = triggers.compute_fire_time_for_countdown(cfg.seconds)
                self._set_fire_time(fire_at)

            elif cfg.trigger == "At time (HH:MM)":
                fire_at = triggers.compute_fire_time_for_at_hhmm(cfg.at_hhmm)
                self._set_fire_time(fire_at)

            elif cfg.trigger == "After app exits":
                if not cfg.target_pid:
                    raise ValueError("No PID selected")
                self.on_tick(SchedulerTick(text=f"Watching PID {cfg.target_pid} ...", phase="waiting"))
                triggers.wait_for_process_exit(self._stop, cfg.target_pid)
                if self._stop.is_set():
                    self._update_active(status="canceled", note="Canceled while waiting for process exit")
                    return
                self.log.info("Process PID %s exited.", cfg.target_pid)

                fire_at = dt.datetime.now().astimezone() + dt.timedelta(seconds=max(0, cfg.process_delay_seconds))
                self._set_fire_time(fire_at)

            elif cfg.trigger == "CPU low for N seconds":
                def cb(cpu, consecutive, target):
                    self.on_tick(SchedulerTick(text=f"CPU {cpu:.1f}% <= {cfg.cpu_threshold:.1f}% for {consecutive}/{target}s", phase="waiting"))
                triggers.wait_for_cpu_low(self._stop, cfg.cpu_threshold, cfg.cpu_duration_s, tick_cb=cb)
                if self._stop.is_set():
                    self._update_active(status="canceled", note="Canceled while waiting for CPU low")
                    return
                self.log.info("CPU low condition satisfied.")
                fire_at = dt.datetime.now().astimezone()
                self._set_fire_time(fire_at)

            elif cfg.trigger == "Disk low for N seconds":
                def cb(kbps, consecutive, target):
                    self.on_tick(SchedulerTick(text=f"Disk {kbps:.1f} KB/s <= {cfg.disk_kbps_threshold:.1f} for {consecutive}/{target}s", phase="waiting"))
                triggers.wait_for_disk_low(self._stop, cfg.disk_kbps_threshold, cfg.disk_duration_s, tick_cb=cb)
                if self._stop.is_set():
                    self._update_active(status="canceled", note="Canceled while waiting for disk low")
                    return
                self.log.info("Disk low condition satisfied.")
                fire_at = dt.datetime.now().astimezone()
                self._set_fire_time(fire_at)

            elif cfg.trigger == "User idle for N minutes":
                def cb(idle, target):
                    self.on_tick(SchedulerTick(text=f"Idle {idle}/{target}s", phase="waiting"))
                triggers.wait_for_user_idle(self._stop, cfg.idle_minutes, tick_cb=cb)
                if self._stop.is_set():
                    self._update_active(status="canceled", note="Canceled while waiting for idle")
                    return
                self.log.info("Idle condition satisfied.")
                fire_at = dt.datetime.now().astimezone()
                self._set_fire_time(fire_at)

            elif cfg.trigger == "Network idle for N seconds":
                def cb(kbps, consecutive, target):
                    self.on_tick(SchedulerTick(text=f"Net {kbps:.1f} KB/s <= {cfg.net_kbps_threshold:.1f} for {consecutive}/{target}s", phase="waiting"))
                triggers.wait_for_network_idle(self._stop, cfg.net_kbps_threshold, cfg.net_duration_s, tick_cb=cb)
                if self._stop.is_set():
                    self._update_active(status="canceled", note="Canceled while waiting for network idle")
                    return
                self.log.info("Network idle condition satisfied.")
                fire_at = dt.datetime.now().astimezone()
                self._set_fire_time(fire_at)

            else:
                raise ValueError(f"Unknown trigger: {cfg.trigger}")

            if not fire_at:
                raise RuntimeError("Internal: fire_at not resolved")

            # -------- integrated final countdown (<=30s) --------
            should_execute = self._wait_until_fire_time(cfg, fire_at)
            if not should_execute:
                return

            # Fullscreen block right before executing (may delay; user asked it)
            if not self._fullscreen_block_if_needed(cfg):
                self._update_active(status="canceled", note="Canceled while fullscreen blocking")
                return

            if self._stop.is_set():
                self._update_active(status="canceled", note="Canceled right before execution")
                return

            self._update_active(phase="firing")
            self._update_active(fired_at_iso=dt.datetime.now().astimezone().isoformat(timespec="seconds"))
            self.log.info("Executing action now: %s", cfg.action)
            execute_action(cfg)

            # In-app execution confirmation for UI summary.
            fired_at = self.active.fired_at_iso if self.active else None
            if fired_at:
                details = [f"In-app execution at {fired_at}."]
            else:
                details = ["In-app execution completed."]
            self._update_active(verified_status="yes", verified_details=details)

            self._update_active(status="completed", note="Action executed")
            self.on_tick(SchedulerTick(text="Done.", phase="waiting"))
        except Exception as e:
            self.log.exception("Task failed: %r", e)
            self._update_active(status="stale", note=f"ERROR: {e!r}")
            self.on_tick(SchedulerTick(text=f"ERROR: {e!r}", phase="waiting"))
        finally:
            self._stop.set()
            self.on_done()
