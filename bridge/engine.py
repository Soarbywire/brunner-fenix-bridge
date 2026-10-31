"""Background worker: keeps the SimConnect link alive and runs the logic each frame."""

import logging
import threading
import time
from dataclasses import dataclass

from .config import Settings
from .logic import RudderBridge, StepResult

log = logging.getLogger(__name__)

RESEND_INTERVAL = 0.5   # s: resend outputs even when unchanged
RECONNECT_INTERVAL = 3.0


@dataclass
class Status:
    connected: bool = False
    message: str = "Starting..."
    aircraft: str = ""
    mode: str = "Idle"          # "Fenix", "Passthrough", "Idle"
    fenix_rudder: float = 0.0
    result: StepResult | None = None
    frames_per_second: float = 0.0


class Engine:
    def __init__(self, settings: Settings, simconnect_factory=None):
        self.settings = settings
        self.logic = RudderBridge(settings)
        self.status = Status()
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sc = None
        self._factory = simconnect_factory
        self._last_t = None
        self._last_trim_sent = None
        self._last_rudder_sent = None
        self._last_send_t = 0.0
        self._frame_count = 0
        self._fps_t = time.perf_counter()
        self._reconnect = threading.Event()
        self.msfs_closed = threading.Event()   # set when MSFS closes after a connection

    # ------------------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, name="bridge", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def apply_settings(self, settings: Settings):
        """New settings; reconnects so changed variable names take effect."""
        with self.lock:
            self.settings = settings
            self.logic = RudderBridge(settings)
        self._reconnect.set()  # the worker thread drops and reopens the link

    def snapshot(self) -> Status:
        with self.lock:
            return Status(**vars(self.status))

    # ------------------------------------------------------------------
    def _set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self.status, k, v)

    def is_fenix(self, path: str) -> bool:
        s = self.settings
        if s.force_active:
            return True
        p = (path or "").lower()
        return any(m.lower() in p for m in s.aircraft_match if m)

    def _make_sc(self):
        if self._factory:
            return self._factory(self)
        from .simconnect import SimConnect
        s = self.settings
        return SimConnect(s.fenix_rudder_lvar, s.pedal_lvar, s.trim_lvar,
                          self.on_inputs, self.on_aircraft, self.on_quit)

    def _drop_connection(self, message):
        sc, self._sc = self._sc, None
        if sc:
            sc.close()
        self._last_t = None
        self._last_trim_sent = self._last_rudder_sent = None
        self._set(connected=False, message=message, mode="Idle")

    def _run(self):
        next_try = 0.0
        while not self._stop.is_set():
            if self._reconnect.is_set():
                self._reconnect.clear()
                self._drop_connection("Settings reloaded, reconnecting...")
                next_try = 0.0
            if self._sc is None:
                now = time.monotonic()
                if now >= next_try:
                    next_try = now + RECONNECT_INTERVAL
                    try:
                        sc = self._make_sc()
                        sc.open()
                        self._sc = sc
                        self.logic.reset()
                        self._set(connected=True, message="Connected to MSFS")
                        log.info("Connected to MSFS")
                    except Exception as e:
                        text = str(e)
                        msg = ("Waiting for MSFS..." if "not running" in text
                               else f"Waiting for MSFS ({text})")
                        self._set(connected=False, message=msg)
                self._stop.wait(0.2)
                continue
            try:
                if self._sc.dispatch() == 0:
                    time.sleep(0.002)
            except Exception as e:
                log.exception("SimConnect error")
                self._drop_connection(f"Connection lost ({e})")
                self.msfs_closed.set()
        self._drop_connection("Stopped")

    # --- SimConnect callbacks ------------------------------------------
    def on_quit(self):
        self._sc = None
        self._set(connected=False, message="MSFS closed, waiting...", mode="Idle")
        self.msfs_closed.set()

    def on_aircraft(self, path: str):
        log.info("Aircraft loaded: %s", path)
        self.logic.reset()
        self._set(aircraft=path)

    def on_inputs(self, fenix_rudder: float, pedal: float):
        now = time.perf_counter()
        dt = 1 / 60 if self._last_t is None else now - self._last_t
        self._last_t = now

        with self.lock:
            logic, s, aircraft = self.logic, self.settings, self.status.aircraft
        if self.is_fenix(aircraft):
            mode, res = "Fenix", logic.step(dt, fenix_rudder, pedal)
            send_rudder = True
        elif s.passthrough_other_aircraft:
            mode, res = "Passthrough", logic.passthrough(pedal)
            send_rudder = True
        else:
            mode, res = "Idle", logic.passthrough(pedal)
            res.rudder_out = 0.0
            send_rudder = False

        self._send(now, res.trim_out, res.rudder_out if send_rudder else None)

        self._frame_count += 1
        fps = None
        if now - self._fps_t >= 1.0:
            fps = self._frame_count / (now - self._fps_t)
            self._frame_count, self._fps_t = 0, now
        with self.lock:
            st = self.status
            st.mode, st.fenix_rudder, st.result = mode, fenix_rudder, res
            if fps is not None:
                st.frames_per_second = fps

    def _send(self, now, trim, rudder):
        sc = self._sc
        if sc is None:
            return
        resend = now - self._last_send_t >= RESEND_INTERVAL
        if resend or self._last_trim_sent is None or abs(trim - self._last_trim_sent) > 1e-5:
            sc.set_trim(trim)
            self._last_trim_sent = trim
        if rudder is not None:
            if resend or self._last_rudder_sent is None or abs(rudder - self._last_rudder_sent) > 1 / 16383:
                sc.set_rudder(-rudder if self.settings.invert_rudder_output else rudder)
                self._last_rudder_sent = rudder
        if resend:
            self._last_send_t = now
