"""Status window."""

import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import APP_ID, APP_NAME, GITHUB_REPO, __version__, startup, updater
from .config import load_settings, settings_dir, settings_path
from .engine import Engine
from .logic import format_trim

log = logging.getLogger(__name__)

REFRESH_MS = 100
GREEN, AMBER, GREY = "#1f9d55", "#c27c0e", "#777777"


class App:
    def __init__(self, root: tk.Tk, auto: bool = False):
        self.root = root
        self.auto = auto  # launched by MSFS: close when MSFS closes
        self.settings = load_settings()
        self.engine = Engine(self.settings)
        self.update_info = None

        root.title(f"{APP_NAME} {__version__}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._build()
        if auto:
            root.iconify()
        startup.refresh_paths()
        self.engine.start()
        self.root.after(REFRESH_MS, self.refresh)
        if self.settings.check_updates_on_start:
            self.check_updates(silent=True)

    # ------------------------------------------------------------------
    def _build(self):
        pad = {"padx": 10, "pady": 3}
        f = ttk.Frame(self.root, padding=10)
        f.grid(sticky="nsew")

        # Update banner (hidden until needed)
        self.banner = ttk.Frame(f)
        self.banner_label = ttk.Label(self.banner, foreground=GREEN)
        self.banner_label.pack(side="left")
        ttk.Button(self.banner, text="Install", command=self.install_update).pack(side="left", padx=6)
        ttk.Button(self.banner, text="What's new",
                   command=lambda: webbrowser.open(self.update_info.page_url)).pack(side="left")

        status = ttk.LabelFrame(f, text="Status", padding=6)
        status.grid(row=1, column=0, sticky="ew")
        self.v_conn = self._row(status, 0, "MSFS")
        self.v_aircraft = self._row(status, 1, "Aircraft")
        self.v_mode = self._row(status, 2, "Mode")

        live = ttk.LabelFrame(f, text="Live values", padding=6)
        live.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.v_trim = self._row(live, 0, "Fenix rudder trim")
        self.v_fenix = self._row(live, 1, "Fenix pedals (N_FC_RUDDER)")
        self.v_trim_out = self._row(live, 2, "Trim to pedals")
        self.v_pedal = self._row(live, 3, "Pedal position")
        self.v_rudder = self._row(live, 4, "Rudder to MSFS")
        self.v_db = self._row(live, 5, "Deadband")
        self.v_fps = self._row(live, 6, "Updates per second")

        opts = ttk.LabelFrame(f, text="Start automatically", padding=6)
        opts.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.var_msfs = tk.BooleanVar(value=startup.msfs_enabled())
        can = startup.exe_path() is not None
        cb1 = ttk.Checkbutton(opts, text="With MSFS: opens minimised when the sim starts, closes with it",
                              variable=self.var_msfs, command=self.toggle_msfs)
        cb1.grid(row=0, column=0, sticky="w")
        if not can:
            cb1.state(["disabled"])

        btns = ttk.Frame(f)
        btns.grid(row=4, column=0, pady=(10, 0), sticky="ew")
        ttk.Button(btns, text="Edit settings", command=self.edit_settings).pack(side="left")
        ttk.Button(btns, text="Reload settings", command=self.reload_settings).pack(side="left", padx=4)
        ttk.Button(btns, text="Check for updates",
                   command=lambda: self.check_updates(silent=False)).pack(side="left")
        ttk.Button(btns, text="Help",
                   command=lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}#readme")
                   ).pack(side="left", padx=4)

    def _row(self, parent, r, label):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 16), pady=1)
        v = tk.StringVar(value="-")
        lbl = ttk.Label(parent, textvariable=v, width=44)
        lbl.grid(row=r, column=1, sticky="w")
        v.label = lbl
        return v

    # ------------------------------------------------------------------
    def refresh(self):
        if self.auto and self.engine.msfs_closed.is_set():
            log.info("MSFS closed; exiting (started with MSFS)")
            self.quit()
            return
        st = self.engine.snapshot()
        self.v_conn.set(st.message)
        self.v_conn.label.configure(foreground=GREEN if st.connected else AMBER)
        self.v_aircraft.set(self._short(st.aircraft) or "-")
        mode_text = {"Fenix": "Active: pedals follow Fenix rudder trim",
                     "Passthrough": "Other aircraft: rudder passthrough",
                     "Idle": "Idle (no Fenix loaded)"}.get(st.mode, st.mode)
        self.v_mode.set(mode_text)
        self.v_mode.label.configure(foreground=GREEN if st.mode == "Fenix" else GREY)
        r = st.result
        if r and st.connected:
            self.v_trim.set(format_trim(r.trim_degrees))
            self.v_fenix.set(f"{st.fenix_rudder:.0f}")
            self.v_trim_out.set(f"{r.trim_out:+.4f}")
            self.v_pedal.set(f"{r.pedal:+.4f}")
            self.v_rudder.set(f"{r.rudder_out:+.4f}")
            self.v_db.set(f"{r.deadband:.3f}")
            self.v_fps.set(f"{st.frames_per_second:.0f}")
        else:
            for v in (self.v_trim, self.v_fenix, self.v_trim_out, self.v_pedal,
                      self.v_rudder, self.v_db, self.v_fps):
                v.set("-")
        self.root.after(REFRESH_MS, self.refresh)

    @staticmethod
    def _short(path, n=44):
        return path if len(path) <= n else "..." + path[-(n - 3):]

    # --- Auto-start ------------------------------------------------------
    def toggle_msfs(self):
        want = self.var_msfs.get()
        exe = startup.exe_path()
        try:
            if want and not startup.msfs_folders():
                raise RuntimeError("Couldn't find an MSFS 2024 or 2020 installation folder.")
            files = startup.set_msfs(want, exe)
            log.info("Start with MSFS %s: %s", want, files)
        except Exception as e:
            self.var_msfs.set(not want)
            messagebox.showerror(APP_NAME, f"Could not change MSFS auto-start.\n{e}")

    # --- Settings --------------------------------------------------------
    def edit_settings(self):
        path = settings_path()
        try:
            if sys.platform == "win32":
                subprocess.Popen(["notepad.exe", path])
            else:
                webbrowser.open(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not open {path}\n{e}")

    def reload_settings(self):
        self.settings = load_settings()
        self.engine.apply_settings(self.settings)
        messagebox.showinfo(APP_NAME, "Settings reloaded.")

    # --- Updates ---------------------------------------------------------
    def check_updates(self, silent: bool):
        def work():
            try:
                info = updater.check_for_update()
                self.root.after(0, lambda: self._update_result(info, silent))
            except Exception as e:
                log.warning("Update check failed: %s", e)
                if not silent:
                    self.root.after(0, lambda: messagebox.showwarning(
                        APP_NAME, f"Could not check for updates.\n{e}"))
        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, info, silent):
        self.update_info = info
        if info:
            self.banner_label.configure(text=f"Version {info.version} is available.")
            self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        elif not silent:
            messagebox.showinfo(APP_NAME, f"You have the latest version ({__version__}).")

    def install_update(self):
        info = self.update_info
        if not info:
            return
        if not updater.can_self_update() or not info.exe_url:
            webbrowser.open(info.page_url)
            return
        if not messagebox.askyesno(APP_NAME, f"Download and install version {info.version}?\n"
                                   "The bridge will restart."):
            return
        self.banner_label.configure(text="Downloading...")

        def work():
            try:
                path = updater.download_update(
                    info, progress=lambda p: self.root.after(
                        0, lambda: self.banner_label.configure(text=f"Downloading... {p:.0%}")))
                self.root.after(0, lambda: self._finish_install(path))
            except Exception as e:
                log.exception("Update failed")
                self.root.after(0, lambda: (
                    self.banner_label.configure(text="Update failed."),
                    messagebox.showerror(APP_NAME, f"Update failed.\n{e}")))
        threading.Thread(target=work, daemon=True).start()

    def _finish_install(self, path):
        updater.install_and_restart(path)
        self.quit()

    # ------------------------------------------------------------------
    def quit(self):
        self.engine.stop()
        self.root.destroy()


def setup_logging():
    os.makedirs(settings_dir(), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.handlers.RotatingFileHandler(
            os.path.join(settings_dir(), "bridge.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
    )


_mutex = None


def already_running(wait: float = 0.0) -> bool:
    """Single instance: a second copy would also send rudder input.
    wait: seconds to keep trying (after an update the old copy is closing)."""
    global _mutex
    if sys.platform != "win32":
        return False
    import ctypes
    import time
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    deadline = time.monotonic() + wait
    while True:
        _mutex = k32.CreateMutexW(None, False, f"Local\\{APP_ID}")
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            return False
        k32.CloseHandle(_mutex)
        _mutex = None
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.5)


def main():
    setup_logging()
    auto = startup.AUTO_ARG in sys.argv
    log.info("%s %s starting %s", APP_NAME, __version__, sys.argv[1:])
    updated = updater.UPDATED_ARG in sys.argv
    if already_running(wait=15.0 if updated else 0.0):
        log.info("Already running; exiting")
        if not (auto or updated):
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(APP_NAME, f"{APP_NAME} is already running.")
            r.destroy()
        return
    updater.cleanup_old()
    root = tk.Tk()
    App(root, auto=auto)
    root.mainloop()
