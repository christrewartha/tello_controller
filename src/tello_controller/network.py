"""Optional Wi-Fi switching: join the Tello's access point, restore afterwards.

Windows uses `netsh`; Linux uses `nmcli`. Use as a context manager so the
previous network is restored on every exit path (including crashes / Ctrl+C):

    with tello_wifi():
        run_app()
"""

from __future__ import annotations

import contextlib
import logging
import platform
import re
import subprocess
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, errors="replace")
    return result.stdout


def parse_current_ssid(netsh_interfaces_output: str) -> str | None:
    # Match "SSID : name" but not "BSSID : ..."; [ \t] so we never span lines.
    m = re.search(r"^[ \t]*SSID[ \t]*:[ \t]*(.+?)[ \t]*$", netsh_interfaces_output, re.MULTILINE)
    return m.group(1) if m else None


def parse_networks(netsh_networks_output: str) -> list[str]:
    names = re.findall(r"^[ \t]*SSID[ \t]+\d+[ \t]*:[ \t]*(.*?)[ \t]*$", netsh_networks_output, re.MULTILINE)
    return [n for n in names if n]


def current_ssid() -> str | None:
    if IS_WINDOWS:
        return parse_current_ssid(_run(["netsh", "wlan", "show", "interfaces"]))
    out = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:]
    return None


def request_scan() -> None:
    """Ask Windows to rescan now. `netsh wlan show networks` only reports a cached
    list that Windows refreshes on its own schedule (often a minute or more), so a
    freshly powered-on Tello wouldn't appear without this. Best effort."""
    if not IS_WINDOWS:
        return  # nmcli rescans as part of available_networks()
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    class WLAN_INTERFACE_INFO(ctypes.Structure):
        _fields_ = [("guid", GUID), ("description", ctypes.c_wchar * 256), ("state", ctypes.c_int)]

    class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("index", wintypes.DWORD), ("items", WLAN_INTERFACE_INFO * 1)]

    try:
        wlan = ctypes.windll.wlanapi
        handle, negotiated = wintypes.HANDLE(), wintypes.DWORD()
        if wlan.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle)) != 0:
            return
        try:
            iface_list = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
            if wlan.WlanEnumInterfaces(handle, None, ctypes.byref(iface_list)) != 0:
                return
            try:
                n = iface_list.contents.count
                items = ctypes.cast(ctypes.byref(iface_list.contents.items), ctypes.POINTER(WLAN_INTERFACE_INFO * n)).contents
                for item in items:
                    wlan.WlanScan(handle, ctypes.byref(item.guid), None, None, None)
            finally:
                wlan.WlanFreeMemory(iface_list)
        finally:
            wlan.WlanCloseHandle(handle, None)
    except (OSError, AttributeError):
        log.debug("WlanScan unavailable", exc_info=True)


def available_networks() -> list[str]:
    if IS_WINDOWS:
        return parse_networks(_run(["netsh", "wlan", "show", "networks"]))
    out = _run(["nmcli", "-t", "-f", "ssid", "dev", "wifi", "list", "--rescan", "yes"])
    return sorted({line for line in out.splitlines() if line})


_OPEN_PROFILE = """<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{name}</name>
  <SSIDConfig><SSID><name>{name}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM><security><authEncryption>
    <authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX>
  </authEncryption></security></MSM>
</WLANProfile>
"""


def _ensure_windows_profile(ssid: str) -> None:
    profiles = _run(["netsh", "wlan", "show", "profiles"])
    if re.search(rf":\s*{re.escape(ssid)}\s*$", profiles, re.MULTILINE):
        return
    # Tello access points are open networks; create a profile so `connect` works.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tello_profile.xml"
        path.write_text(_OPEN_PROFILE.format(name=escape(ssid)), encoding="utf-8")
        _run(["netsh", "wlan", "add", "profile", f"filename={path}", "user=current"])


def connect(ssid: str, timeout_s: float = 20.0) -> bool:
    log.info("Connecting to Wi-Fi %s ...", ssid)
    if IS_WINDOWS:
        _ensure_windows_profile(ssid)
        _run(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"])
    else:
        _run(["nmcli", "dev", "wifi", "connect", ssid])
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if current_ssid() == ssid:
            time.sleep(1.0)  # let DHCP settle
            return True
        time.sleep(0.5)
    return False


def is_tello(ssid: str) -> bool:
    return ssid.upper().startswith("TELLO")


def choose_tello_network(networks: list[str], interactive: bool = True) -> str | None:
    tellos = [n for n in networks if is_tello(n)]
    if len(tellos) <= 1 or not interactive:
        return tellos[0] if tellos else None
    print("More than one Tello is visible. Which one?")
    for i, n in enumerate(tellos, 1):
        print(f"  {i}. {n}")
    try:
        choice = int(input("> "))
    except (ValueError, EOFError):
        return None
    return tellos[choice - 1] if 1 <= choice <= len(tellos) else None


def wait_for_network(
    ssid: str | None = None,
    poll_s: float = 3.0,
    timeout_s: float | None = None,
    *,
    scan=request_scan,
    list_networks=available_networks,
    sleep=time.sleep,
    clock=time.monotonic,
) -> list[str]:
    """Rescan every `poll_s` until `ssid` (or any TELLO-*) is visible.

    Returns the matching SSIDs. Raises TimeoutError after `timeout_s` (None = wait
    forever; Ctrl+C to cancel).
    """
    def matches(networks: list[str]) -> list[str]:
        return [n for n in networks if (n == ssid if ssid else is_tello(n))]

    found = matches(list_networks())  # cached list first: instant if it's already there
    if found:
        return found
    what = ssid or "a TELLO-xxxx network"
    print(f"Waiting for {what} to appear. Switch the drone on (Ctrl+C to cancel)", end="", flush=True)
    start = clock()
    try:
        while True:
            scan()
            sleep(poll_s)  # a scan takes a few seconds to complete
            found = matches(list_networks())
            if found:
                return found
            if timeout_s is not None and clock() - start >= timeout_s:
                raise TimeoutError(f"{what} did not appear within {timeout_s:.0f}s")
            print(".", end="", flush=True)
    finally:
        print()


def connect_with_retry(ssid: str, attempts: int = 3) -> bool:
    for attempt in range(1, attempts + 1):
        if connect(ssid, timeout_s=15.0):
            return True
        log.warning("Couldn't join %s (attempt %d/%d)", ssid, attempt, attempts)
        request_scan()
        time.sleep(2.0)
    return False


@contextlib.contextmanager
def tello_wifi(ssid: str | None = None, wait_timeout_s: float | None = None):
    """Join the Tello network for the duration of the block, then restore.

    If the drone's network isn't visible yet, keeps rescanning until it is.
    """
    previous = current_ssid()
    if previous and (previous == ssid or (not ssid and is_tello(previous))):
        log.info("Already on %s", previous)
        yield previous
        return
    found = wait_for_network(ssid, timeout_s=wait_timeout_s)
    target = ssid or choose_tello_network(found)
    if target is None:
        raise RuntimeError("No Tello selected")
    if not connect_with_retry(target):
        raise RuntimeError(f"Could not connect to {target}")
    try:
        yield target
    finally:
        if previous:
            log.info("Restoring Wi-Fi %s", previous)
            if IS_WINDOWS:
                _run(["netsh", "wlan", "connect", f"name={previous}"])
            else:
                _run(["nmcli", "dev", "wifi", "connect", previous])
