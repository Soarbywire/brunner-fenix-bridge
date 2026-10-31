"""Optional automatic start: with MSFS (exe.xml) or with Windows (Run key).

MSFS launches every enabled <Launch.Addon> in exe.xml when the sim starts.
Only the bridge's own entry is ever added, updated or removed; other
add-ons' entries are left untouched, and exe.xml is backed up before the
first change.
"""

import logging
import os
import shutil
import sys
import xml.etree.ElementTree as ET

from . import APP_NAME, APP_ID

log = logging.getLogger(__name__)

AUTO_ARG = "--auto"            # launched by MSFS: start minimised, close with MSFS
MINIMISED_ARG = "--minimized"  # launched with Windows: start minimised
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

EXE_XML_TEMPLATE = """<?xml version="1.0" encoding="Windows-1252"?>
<SimBase.Document Type="SimConnect" version="1,0">
  <Descr>Auto launch external applications on MSFS start</Descr>
  <Filename>exe.xml</Filename>
  <Disabled>False</Disabled>
  <Launch.ManualLoad>False</Launch.ManualLoad>
</SimBase.Document>
"""


def exe_path() -> str | None:
    """Path of the running .exe, or None when running from source."""
    return sys.executable if getattr(sys, "frozen", False) else None


# --- MSFS (exe.xml) -------------------------------------------------------
def msfs_folders(env=None) -> list[str]:
    """Existing MSFS folders where exe.xml lives (Store and Steam, 2024 and 2020)."""
    env = env if env is not None else os.environ
    local, roaming = env.get("LOCALAPPDATA", ""), env.get("APPDATA", "")
    candidates = [
        os.path.join(local, "Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache"),
        os.path.join(roaming, "Microsoft Flight Simulator 2024"),
        os.path.join(local, "Packages", "Microsoft.FlightSimulator_8wekyb3d8bbwe", "LocalCache"),
        os.path.join(roaming, "Microsoft Flight Simulator"),
    ]
    return [c for c in candidates if (local or roaming) and os.path.isdir(c)]


def _load(path: str) -> ET.ElementTree:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))  # keep comments
        return ET.parse(path, parser)
    return ET.ElementTree(ET.fromstring(EXE_XML_TEMPLATE))


def _ours(root: ET.Element):
    return [a for a in root.findall("Launch.Addon")
            if (a.findtext("Name") or "").strip() == APP_NAME]


def _save(tree: ET.ElementTree, path: str):
    if os.path.exists(path):
        backup = path + f".{APP_ID}.bak"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="Windows-1252", xml_declaration=True)


def msfs_enabled(folders=None) -> bool:
    for folder in folders if folders is not None else msfs_folders():
        path = os.path.join(folder, "exe.xml")
        try:
            if os.path.exists(path) and _ours(_load(path).getroot()):
                return True
        except ET.ParseError:
            log.warning("Could not read %s", path)
    return False


def set_msfs(enabled: bool, exe: str, folders=None) -> list[str]:
    """Add or remove the bridge in every exe.xml. Returns the files changed."""
    changed = []
    for folder in folders if folders is not None else msfs_folders():
        path = os.path.join(folder, "exe.xml")
        tree = _load(path)  # raises ParseError on a broken file: never overwrite it
        root = tree.getroot()
        existing = _ours(root)
        dirty = False
        if enabled:
            if existing:
                addon = existing[0]
            else:
                addon, dirty = ET.SubElement(root, "Launch.Addon"), True
            for extra in existing[1:]:
                root.remove(extra)
                dirty = True
            for tag, text in (("Name", APP_NAME), ("Disabled", "False"),
                              ("Path", exe), ("CommandLine", AUTO_ARG)):
                el = addon.find(tag)
                if el is None:
                    el = ET.SubElement(addon, tag)
                if (el.text or "").strip() != text:
                    el.text, dirty = text, True
        else:
            for a in existing:
                root.remove(a)
                dirty = True
        if not dirty:
            continue
        _save(tree, path)
        changed.append(path)
    return changed


# --- Windows (Run key) ----------------------------------------------------
def windows_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
            return True
    except OSError:
        return False


def set_windows(enabled: bool, exe: str) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, f'"{exe}" {MINIMISED_ARG}')
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass


def refresh_paths() -> None:
    """If the exe was moved or updated, point enabled entries at its current path."""
    exe = exe_path()
    if not exe:
        return
    try:
        if msfs_enabled():
            set_msfs(True, exe)
        if windows_enabled():
            set_windows(True, exe)
    except Exception:
        log.exception("Could not refresh auto-start entries")
