from __future__ import annotations

import datetime as dt
import time
from typing import Optional, Tuple

import psutil

from win.idle import get_idle_seconds


def _sleep_stop(stop_event, seconds: float) -> None:
    stop_event.wait(timeout=seconds)


def compute_fire_time_for_countdown(seconds: int) -> dt.datetime:
    return dt.datetime.now().astimezone() + dt.timedelta(seconds=max(0, seconds))


def compute_fire_time_for_at_hhmm(hhmm: str) -> dt.datetime:
    hh, mm = hhmm.strip().split(":")
    hh_i, mm_i = int(hh), int(mm)
    now = dt.datetime.now().astimezone()
    target = now.replace(hour=hh_i, minute=mm_i, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return target


def wait_for_process_exit(stop_event, pid: int) -> None:
    while not stop_event.is_set():
        if not psutil.pid_exists(pid):
            return
        _sleep_stop(stop_event, 1.0)


def wait_for_cpu_low(stop_event, threshold: float, duration_s: int, tick_cb=None) -> None:
    consecutive = 0
    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=1.0)
        if cpu <= threshold:
            consecutive += 1
        else:
            consecutive = 0
        if tick_cb:
            tick_cb(cpu=cpu, consecutive=consecutive, target=duration_s)
        if consecutive >= duration_s:
            return


def wait_for_disk_low(stop_event, kbps_threshold: float, duration_s: int, tick_cb=None) -> None:
    consecutive = 0
    last = psutil.disk_io_counters()
    last_total = last.read_bytes + last.write_bytes
    last_t = time.time()

    while not stop_event.is_set():
        _sleep_stop(stop_event, 1.0)
        now = psutil.disk_io_counters()
        total = now.read_bytes + now.write_bytes
        t = time.time()
        dt_s = max(0.001, t - last_t)
        bps = (total - last_total) / dt_s
        kbps = bps / 1024.0
        last_total, last_t = total, t

        if kbps <= kbps_threshold:
            consecutive += 1
        else:
            consecutive = 0
        if tick_cb:
            tick_cb(kbps=kbps, consecutive=consecutive, target=duration_s)
        if consecutive >= duration_s:
            return


def wait_for_user_idle(stop_event, minutes: int, tick_cb=None) -> None:
    target = minutes * 60
    while not stop_event.is_set():
        idle = int(get_idle_seconds())
        if tick_cb:
            tick_cb(idle=idle, target=target)
        if idle >= target:
            return
        _sleep_stop(stop_event, 1.0)


def wait_for_network_idle(stop_event, kbps_threshold: float, duration_s: int, tick_cb=None) -> None:
    consecutive = 0
    last = psutil.net_io_counters()
    last_total = last.bytes_sent + last.bytes_recv
    last_t = time.time()

    while not stop_event.is_set():
        _sleep_stop(stop_event, 1.0)
        now = psutil.net_io_counters()
        total = now.bytes_sent + now.bytes_recv
        t = time.time()
        dt_s = max(0.001, t - last_t)
        bps = (total - last_total) / dt_s
        kbps = bps / 1024.0
        last_total, last_t = total, t

        if kbps <= kbps_threshold:
            consecutive += 1
        else:
            consecutive = 0
        if tick_cb:
            tick_cb(kbps=kbps, consecutive=consecutive, target=duration_s)
        if consecutive >= duration_s:
            return
