from __future__ import annotations

import datetime as dt
import json
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

from core.models import TaskConfig, ActiveTask


EVENT_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


@dataclass
class VerificationResult:
    status: str          # yes | likely | no | unknown
    details: List[str]   # evidence lines


def _parse_dt(s: str) -> Optional[dt.datetime]:
    try:
        # Handles 'Z' and offsets
        if s.startswith("/Date(") and s.endswith(")/"):
            ms = int(s[len("/Date("):-2])
            return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def _to_aware_local(t: dt.datetime) -> dt.datetime:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return t.astimezone()


def _powershell_json(cmd: str) -> Optional[dict]:
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=False
    )
    if p.returncode != 0:
        return None
    out = (p.stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def get_scheduled_task_info(task_name: str) -> Optional[dict]:
    """
    Uses Get-ScheduledTaskInfo to avoid parsing localized schtasks output.
    """
    # TaskName in PS is often like "\Name". Ensure leading backslash.
    tn = task_name
    if not tn.startswith("\\"):
        tn = "\\" + tn
    # Convert to JSON for stable parsing
    ps = (
        f"$i = Get-ScheduledTaskInfo -TaskName '{tn}'; "
        "$o = [pscustomobject]@{"
        "LastRunTime=$i.LastRunTime; "
        "LastTaskResult=$i.LastTaskResult; "
        "NextRunTime=$i.NextRunTime; "
        "NumberOfMissedRuns=$i.NumberOfMissedRuns"
        "}; $o | ConvertTo-Json -Compress"
    )
    return _powershell_json(ps)


def _wevtutil_query_xml(log_name: str, xpath: str, count: int = 250) -> Optional[str]:
    """
    wevtutil qe <log> /q:<xpath> /f:xml /c:<count> /rd:true
    """
    p = subprocess.run(
        ["wevtutil", "qe", log_name, "/q:" + xpath, "/f:xml", f"/c:{count}", "/rd:true"],
        capture_output=True,
        text=True,
        check=False
    )
    if p.returncode != 0:
        return None
    return p.stdout


def _parse_events(xml_text: str) -> List[Tuple[dt.datetime, int, str, str]]:
    """
    Returns list of (time, event_id, provider, raw_xml_snippet)
    """
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    events: List[Tuple[dt.datetime, int, str, str]] = []
    for ev in root.findall("e:Event", EVENT_NS):
        sys = ev.find("e:System", EVENT_NS)
        if sys is None:
            continue
        eid_node = sys.find("e:EventID", EVENT_NS)
        prov_node = sys.find("e:Provider", EVENT_NS)
        tc_node = sys.find("e:TimeCreated", EVENT_NS)
        if eid_node is None or tc_node is None:
            continue
        try:
            eid = int(eid_node.text or "0")
        except Exception:
            continue
        prov = (prov_node.attrib.get("Name") if prov_node is not None else "") or ""
        ts = tc_node.attrib.get("SystemTime", "")
        t = _parse_dt(ts)
        if not t:
            continue
        # Keep whole event xml snippet for substring matching (shutdown.exe etc)
        raw = ET.tostring(ev, encoding="unicode", method="xml")
        events.append((t, eid, prov, raw))
    return events


def _filter_by_window(
    events: List[Tuple[dt.datetime, int, str, str]],
    start: dt.datetime,
    end: dt.datetime
) -> List[Tuple[dt.datetime, int, str, str]]:
    out = []
    for t, eid, prov, raw in events:
        if start <= t <= end:
            out.append((t, eid, prov, raw))
    return out


def _event_evidence_for_action(cfg: TaskConfig) -> Dict[str, Dict]:
    """
    Defines per-action logs and event IDs to search.
    """
    a = cfg.action
    if a in ("Shutdown", "Restart", "Restart (Safe Mode minimal)", "Restart (Safe Mode + Networking)"):
        return {
            "System": {
                "ids": [1074, 6006],
                "hints": ["shutdown.exe", "User32", "EVENTLOG"],
                "window_minutes": 12,
            }
        }
    if a in ("Sleep", "Hibernate"):
        return {
            "System": {
                "ids": [42, 187],
                "hints": ["Kernel-Power", "SetSuspendState"],
                "window_minutes": 12,
            }
        }
    if a == "Lock":
        # Requires Audit Other Logon/Logoff Events to be enabled (4800/4801).
        return {
            "Security": {
                "ids": [4800],
                "hints": ["workstation was locked", "4800"],
                "window_minutes": 5,
            }
        }
    return {}  # unknown action


def verify_execution(logger, task: ActiveTask) -> VerificationResult:
    """
    Tries to verify whether the action actually happened, after reboot / app restart.

    Logic:
      1) If task has scheduled_task_name -> check Task Scheduler LastRunTime/LastTaskResult (strong signal).
      2) Check Event Logs near expected fire time for action-specific evidence.
      3) Combine into status:
         - yes: scheduler says ran successfully OR event evidence is strong
         - likely: scheduler ran but event evidence missing (e.g. lock auditing off), or only weak evidence
         - no: scheduler did not run and no evidence
         - unknown: cannot access logs / no suitable signals
    """
    cfg = TaskConfig.from_dict(task.config)

    details: List[str] = []
    now = dt.datetime.now().astimezone()

    # Choose "expected time" for windowing
    t0 = None
    if task.next_fire_time_iso:
        t0 = _parse_dt(task.next_fire_time_iso)
    if not t0 and getattr(task, "fired_at_iso", None):
        t0 = _parse_dt(getattr(task, "fired_at_iso"))
    if not t0:
        return VerificationResult("unknown", ["No expected time stored to correlate."])
    t0 = _to_aware_local(t0)

    scheduler_ok = None  # True/False/None
    # --- Task Scheduler signal
    if task.scheduled_task_name:
        info = get_scheduled_task_info(task.scheduled_task_name)
        if info is None:
            details.append(f"TaskScheduler: no info for {task.scheduled_task_name} (task may be deleted/missing).")
        else:
            lrt = info.get("LastRunTime")
            lrr = info.get("LastTaskResult")
            lrt_dt = _parse_dt(lrt) if isinstance(lrt, str) else None
            if lrt_dt:
                lrt_dt = _to_aware_local(lrt_dt)
            details.append(f"TaskScheduler: LastRunTime={lrt} LastTaskResult={lrr}")
            # Interpret: ran near expected time and result 0
            if lrt_dt and abs((lrt_dt - t0).total_seconds()) <= 15 * 60 and int(lrr) == 0:
                scheduler_ok = True
            elif now > (t0 + dt.timedelta(minutes=15)):
                scheduler_ok = False

    # --- Event Log signal
    ev_map = _event_evidence_for_action(cfg)
    evidence_hits = 0
    any_log_access = False

    for log_name, spec in ev_map.items():
        ids = spec["ids"]
        window = int(spec["window_minutes"])
        start = (t0 - dt.timedelta(minutes=window)).astimezone(dt.timezone.utc)
        end = (t0 + dt.timedelta(minutes=window)).astimezone(dt.timezone.utc)

        # XPath: *[System[(EventID=1074 or EventID=6006)]]
        or_expr = " or ".join([f"EventID={i}" for i in ids])
        xpath = f"*[System[({or_expr})]]"

        xml = _wevtutil_query_xml(log_name, xpath, count=300)
        if xml is None:
            details.append(f"EventLog({log_name}): no access or query failed.")
            continue

        any_log_access = True
        events = _parse_events(xml)
        events = _filter_by_window(events, start, end)

        if not events:
            details.append(f"EventLog({log_name}): no matching events in window.")
            continue

        # Heuristic: count matches; also try to match hints in raw XML
        hints = [h.lower() for h in spec.get("hints", [])]
        for t, eid, prov, raw in events[:10]:
            raw_l = raw.lower()
            hint_ok = any(h in raw_l for h in hints) if hints else True
            if hint_ok:
                evidence_hits += 1
                details.append(f"EventLog({log_name}) hit: id={eid} provider={prov} time={t.isoformat()}")
        if evidence_hits == 0:
            # still record first one
            t, eid, prov, _ = events[0]
            details.append(f"EventLog({log_name}) weak hit: id={eid} provider={prov} time={t.isoformat()}")

    # --- Combine
    if scheduler_ok is True:
        if evidence_hits > 0 or not any_log_access:
            return VerificationResult("yes", details + ["Decision: YES (Task Scheduler indicates success)."])
        return VerificationResult("likely", details + ["Decision: LIKELY (Task Scheduler success, but no event evidence)."])

    if evidence_hits > 0:
        return VerificationResult("yes", details + ["Decision: YES (Event log evidence found)."])

    if scheduler_ok is False:
        if any_log_access:
            return VerificationResult("no", details + ["Decision: NO (Scheduler did not run and no event evidence)."])
        return VerificationResult("no", details + ["Decision: NO (Task Scheduler indicates no run)."])

    return VerificationResult("unknown", details + ["Decision: UNKNOWN (insufficient signals)."])
