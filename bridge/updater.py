"""Update check against the GitHub releases of this project.

A release must contain BrunnerFenixBridge.exe and, ideally,
BrunnerFenixBridge.exe.sha256 (the build workflow attaches both).
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass

from . import APP_ID, GITHUB_REPO, __version__

log = logging.getLogger(__name__)

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXE_NAME = f"{APP_ID}.exe"
TIMEOUT = 15


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    exe_url: str | None
    exe_size: int | None
    sha256_url: str | None


def parse_version(text: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Non-numeric parts are ignored."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_ID}/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def check_for_update() -> UpdateInfo | None:
    """Returns UpdateInfo if a newer release exists, else None. Raises on network errors."""
    data = json.loads(_get(API_LATEST))
    tag = data.get("tag_name", "")
    if not is_newer(tag):
        return None
    exe = sha = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.lower() == EXE_NAME.lower():
            exe = a
        elif name.lower() == (EXE_NAME + ".sha256").lower():
            sha = a
    return UpdateInfo(
        version=tag.lstrip("vV"),
        notes=data.get("body") or "",
        page_url=data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
        exe_url=exe["browser_download_url"] if exe else None,
        exe_size=exe.get("size") if exe else None,
        sha256_url=sha["browser_download_url"] if sha else None,
    )


def can_self_update() -> bool:
    """Only the packaged .exe can replace itself."""
    return getattr(sys, "frozen", False) and sys.platform == "win32"


def download_update(info: UpdateInfo, progress=None) -> str:
    """Download and verify the new exe. Returns its path next to the running exe."""
    if not info.exe_url:
        raise RuntimeError("This release has no BrunnerFenixBridge.exe attached")
    target_dir = os.path.dirname(sys.executable)
    new_path = os.path.join(target_dir, f"{APP_ID}.new.exe")

    req = urllib.request.Request(info.exe_url, headers={"User-Agent": f"{APP_ID}/{__version__}"})
    h = hashlib.sha256()
    done = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(new_path, "wb") as f:
        total = info.exe_size or int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)

    try:
        if info.exe_size and done != info.exe_size:
            raise RuntimeError(f"Download incomplete ({done} of {info.exe_size} bytes)")
        if info.sha256_url:
            expected = _get(info.sha256_url).decode("ascii", "replace").split()[0].strip().lower()
            if h.hexdigest() != expected:
                raise RuntimeError("Downloaded file failed the checksum check")
    except Exception:
        os.remove(new_path)
        raise
    return new_path


def install_and_restart(new_path: str) -> None:
    """Swap the exe once this process exits, then start the new version."""
    exe = sys.executable
    pid = os.getpid()
    script = os.path.join(tempfile.gettempdir(), f"{APP_ID}_update.cmd")
    with open(script, "w", encoding="ascii") as f:
        f.write(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  timeout /t 1 /nobreak >NUL
  goto wait
)
move /Y "{new_path}" "{exe}" >NUL
start "" "{exe}"
del "%~f0"
""")
    flags = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen(["cmd", "/c", script], creationflags=flags, close_fds=True)
