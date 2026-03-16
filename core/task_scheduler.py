from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import datetime as dt
import getpass
import ctypes
from ctypes import wintypes
import xml.sax.saxutils as xmlutils


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def task_exists(task_name: str) -> bool:
    p = _run(["schtasks", "/query", "/tn", task_name])
    return p.returncode == 0


def delete_task(task_name: str) -> None:
    _run(["schtasks", "/delete", "/tn", task_name, "/f"])


def _local_iso_with_offset(t: dt.datetime) -> str:
    # Use local time without offset for Task Scheduler compatibility.
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    t = t.astimezone()
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def _current_user_sid() -> Optional[str]:
    try:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32

        TOKEN_QUERY = 0x0008
        TokenUser = 1

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            return None

        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        if size.value == 0:
            kernel32.CloseHandle(token)
            return None

        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, TokenUser, buf, size, ctypes.byref(size)):
            kernel32.CloseHandle(token)
            return None

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

        sid_and_attrs = ctypes.cast(buf, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents
        str_sid = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_and_attrs.Sid, ctypes.byref(str_sid)):
            kernel32.CloseHandle(token)
            return None

        sid = str_sid.value
        advapi32.LocalFree(str_sid)
        kernel32.CloseHandle(token)
        return sid
    except Exception:
        return None


@dataclass
class ScheduledTaskSpec:
    name: str
    run_at: dt.datetime
    command: str
    runlevel_highest: bool = False
    author: str = "PowerTimer"
    description: str = "PowerTimer scheduled action"
    # InteractiveToken -> runs only if user is logged on, no password required.
    use_interactive_token: bool = True


def build_task_xml(spec: ScheduledTaskSpec) -> str:
    start = _local_iso_with_offset(spec.run_at)
    cmd = spec.command

    # Escape for XML
    cmd_xml = xmlutils.escape(cmd)
    author_xml = xmlutils.escape(spec.author)
    desc_xml = xmlutils.escape(spec.description)

    # Principal
    # InteractiveToken (no password prompts). Otherwise SYSTEM with Highest.
    if spec.use_interactive_token:
        sid = _current_user_sid()
        userid = xmlutils.escape(sid) if sid else xmlutils.escape(getpass.getuser())
        logon_type = "InteractiveToken"
        run_level = "HighestAvailable" if spec.runlevel_highest else "LeastPrivilege"
    else:
        userid = "S-1-5-18"  # SYSTEM
        logon_type = "ServiceAccount"
        run_level = "HighestAvailable"

    # Minimal Task Scheduler 2.0 XML
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{author_xml}</Author>
    <Description>{desc_xml}</Description>
  </RegistrationInfo>

  <Triggers>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>

  <Principals>
    <Principal id="Author">
      <UserId>{userid}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>{run_level}</RunLevel>
    </Principal>
  </Principals>

  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>

  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c {cmd_xml}</Arguments>
    </Exec>
  </Actions>
</Task>
"""
    return xml


def create_task_from_xml(task_name: str, xml_path: Path) -> subprocess.CompletedProcess:
    return _run(["schtasks", "/create", "/tn", task_name, "/xml", str(xml_path), "/f"])


def create_task(spec: ScheduledTaskSpec, tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    xml_content = build_task_xml(spec)

    xml_path = tmp_dir / f"{spec.name.replace('\\', '_').replace('/', '_')}.xml"
    # Task Scheduler examples often use UTF-16 XML.
    xml_path.write_text(xml_content, encoding="utf-16")

    res = create_task_from_xml(spec.name, xml_path)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create scheduled task: {res.stderr.strip() or res.stdout.strip()}")
    try:
        xml_path.unlink(missing_ok=True)
    except Exception:
        pass
