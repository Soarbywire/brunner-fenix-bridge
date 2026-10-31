"""Minimal SimConnect client using ctypes (Windows only).

Only what the bridge needs: read and write L:vars through data definitions,
send the AXIS_RUDDER_SET event, and track which aircraft is loaded.
"""

import ctypes
import logging
import os
import sys
from ctypes import (POINTER, Structure, byref, c_char, c_char_p, c_double,
                    c_float, c_int32, c_uint32, c_void_p, sizeof)

log = logging.getLogger(__name__)

DWORD = c_uint32
HANDLE = c_void_p
HRESULT = c_int32
MAX_PATH = 260

# Enums / constants
SIMCONNECT_OBJECT_ID_USER = 0
SIMCONNECT_UNUSED = 0xFFFFFFFF
SIMCONNECT_DATATYPE_FLOAT64 = 4
SIMCONNECT_PERIOD_SIM_FRAME = 3
SIMCONNECT_GROUP_PRIORITY_HIGHEST = 1
SIMCONNECT_EVENT_FLAG_GROUPID_IS_PRIORITY = 0x10

RECV_ID_EXCEPTION = 1
RECV_ID_OPEN = 2
RECV_ID_QUIT = 3
RECV_ID_EVENT = 4
RECV_ID_EVENT_FILENAME = 6
RECV_ID_SIMOBJECT_DATA = 8
RECV_ID_SYSTEM_STATE = 15


class RECV(Structure):
    _fields_ = [("dwSize", DWORD), ("dwVersion", DWORD), ("dwID", DWORD)]


class RECV_EXCEPTION(Structure):
    _fields_ = [("hdr", RECV), ("dwException", DWORD), ("dwSendID", DWORD), ("dwIndex", DWORD)]


class RECV_EVENT(Structure):
    _fields_ = [("hdr", RECV), ("uGroupID", DWORD), ("uEventID", DWORD), ("dwData", DWORD)]


class RECV_EVENT_FILENAME(Structure):
    _fields_ = [("evt", RECV_EVENT), ("szFileName", c_char * MAX_PATH), ("dwFlags", DWORD)]


class RECV_SIMOBJECT_DATA(Structure):
    _fields_ = [("hdr", RECV), ("dwRequestID", DWORD), ("dwObjectID", DWORD),
                ("dwDefineID", DWORD), ("dwFlags", DWORD), ("dwentrynumber", DWORD),
                ("dwoutof", DWORD), ("dwDefineCount", DWORD)]


class RECV_SYSTEM_STATE(Structure):
    _fields_ = [("hdr", RECV), ("dwRequestID", DWORD), ("dwInteger", DWORD),
                ("fFloat", c_float), ("szString", c_char * MAX_PATH)]


# Our IDs
DEF_INPUTS = 1      # [fenix rudder, pedal]
DEF_TRIM = 2        # [trim]
REQ_INPUTS = 1
REQ_AIRCRAFT = 2
EVT_RUDDER = 1
EVT_AIRCRAFT_LOADED = 2
EVT_SIM_START = 3
GROUP_MAIN = 1


def _dll_candidates():
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
    yield os.path.join(here, "SimConnect.dll")
    yield os.path.join(os.path.dirname(os.path.abspath(__file__)), "SimConnect.dll")
    yield os.path.join(os.getcwd(), "SimConnect.dll")
    for env in ("MSFS2024_SDK", "MSFS_SDK"):
        root = os.environ.get(env)
        if root:
            yield os.path.join(root, "SimConnect SDK", "lib", "SimConnect.dll")
    yield "SimConnect.dll"  # system search path


def load_dll():
    last = None
    for path in _dll_candidates():
        if path != "SimConnect.dll" and not os.path.exists(path):
            continue
        try:
            dll = ctypes.WinDLL(path)
            log.info("Loaded SimConnect from %s", path)
            return dll
        except OSError as e:
            last = e
    raise OSError(f"SimConnect.dll not found ({last})")


class SimConnectError(Exception):
    pass


class SimConnect:
    """Thin wrapper. Call dispatch() often; it invokes the callbacks."""

    def __init__(self, fenix_lvar, pedal_lvar, trim_lvar,
                 on_inputs, on_aircraft, on_quit):
        self.dll = load_dll()
        self._bind()
        self.handle = HANDLE()
        self.fenix_lvar = fenix_lvar
        self.pedal_lvar = pedal_lvar
        self.trim_lvar = trim_lvar
        self.on_inputs = on_inputs      # (fenix_rudder, pedal)
        self.on_aircraft = on_aircraft  # (path)
        self.on_quit = on_quit

    def _bind(self):
        d = self.dll
        d.SimConnect_Open.argtypes = [POINTER(HANDLE), c_char_p, c_void_p, DWORD, HANDLE, DWORD]
        d.SimConnect_Close.argtypes = [HANDLE]
        d.SimConnect_AddToDataDefinition.argtypes = [HANDLE, DWORD, c_char_p, c_char_p, DWORD, c_float, DWORD]
        d.SimConnect_RequestDataOnSimObject.argtypes = [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD]
        d.SimConnect_SetDataOnSimObject.argtypes = [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD, c_void_p]
        d.SimConnect_MapClientEventToSimEvent.argtypes = [HANDLE, DWORD, c_char_p]
        d.SimConnect_TransmitClientEvent.argtypes = [HANDLE, DWORD, DWORD, DWORD, DWORD, DWORD]
        d.SimConnect_SubscribeToSystemEvent.argtypes = [HANDLE, DWORD, c_char_p]
        d.SimConnect_RequestSystemState.argtypes = [HANDLE, DWORD, c_char_p]
        d.SimConnect_GetNextDispatch.argtypes = [HANDLE, POINTER(POINTER(RECV)), POINTER(DWORD)]
        for name in ("SimConnect_Open", "SimConnect_Close", "SimConnect_AddToDataDefinition",
                     "SimConnect_RequestDataOnSimObject", "SimConnect_SetDataOnSimObject",
                     "SimConnect_MapClientEventToSimEvent", "SimConnect_TransmitClientEvent",
                     "SimConnect_SubscribeToSystemEvent", "SimConnect_RequestSystemState",
                     "SimConnect_GetNextDispatch"):
            getattr(d, name).restype = HRESULT

    def _check(self, hr, what):
        if hr < 0:
            raise SimConnectError(f"{what} failed (0x{hr & 0xFFFFFFFF:08X})")

    # ------------------------------------------------------------------
    def open(self, client_name=b"Brunner Fenix Bridge"):
        hr = self.dll.SimConnect_Open(byref(self.handle), client_name, None, 0, None, 0)
        if hr < 0:
            raise SimConnectError("MSFS not running")
        d, h = self.dll, self.handle
        add = d.SimConnect_AddToDataDefinition
        self._check(add(h, DEF_INPUTS, self.fenix_lvar.encode(), b"Number",
                        SIMCONNECT_DATATYPE_FLOAT64, 0.0, SIMCONNECT_UNUSED), "define fenix")
        self._check(add(h, DEF_INPUTS, self.pedal_lvar.encode(), b"Number",
                        SIMCONNECT_DATATYPE_FLOAT64, 0.0, SIMCONNECT_UNUSED), "define pedal")
        self._check(add(h, DEF_TRIM, self.trim_lvar.encode(), b"Number",
                        SIMCONNECT_DATATYPE_FLOAT64, 0.0, SIMCONNECT_UNUSED), "define trim")
        self._check(d.SimConnect_RequestDataOnSimObject(
            h, REQ_INPUTS, DEF_INPUTS, SIMCONNECT_OBJECT_ID_USER,
            SIMCONNECT_PERIOD_SIM_FRAME, 0, 0, 0, 0), "request inputs")
        self._check(d.SimConnect_MapClientEventToSimEvent(h, EVT_RUDDER, b"AXIS_RUDDER_SET"), "map rudder")
        self._check(d.SimConnect_SubscribeToSystemEvent(h, EVT_AIRCRAFT_LOADED, b"AircraftLoaded"), "sub aircraft")
        self._check(d.SimConnect_SubscribeToSystemEvent(h, EVT_SIM_START, b"SimStart"), "sub simstart")
        self.request_aircraft()

    def request_aircraft(self):
        self.dll.SimConnect_RequestSystemState(self.handle, REQ_AIRCRAFT, b"AircraftLoaded")

    def close(self):
        if self.handle:
            try:
                self.dll.SimConnect_Close(self.handle)
            except Exception:
                pass
            self.handle = HANDLE()

    # ------------------------------------------------------------------
    def set_trim(self, value: float):
        v = c_double(value)
        self._check(self.dll.SimConnect_SetDataOnSimObject(
            self.handle, DEF_TRIM, SIMCONNECT_OBJECT_ID_USER, 0, 0, sizeof(v), byref(v)), "set trim")

    def set_rudder(self, ratio: float):
        """ratio -1..1 -> AXIS_RUDDER_SET -16383..16383."""
        value = int(round(max(-1.0, min(1.0, ratio)) * 16383)) & 0xFFFFFFFF
        self._check(self.dll.SimConnect_TransmitClientEvent(
            self.handle, SIMCONNECT_OBJECT_ID_USER, EVT_RUDDER, value,
            SIMCONNECT_GROUP_PRIORITY_HIGHEST, SIMCONNECT_EVENT_FLAG_GROUPID_IS_PRIORITY), "send rudder")

    def dispatch(self) -> int:
        """Process all pending messages. Returns how many were handled."""
        count = 0
        p = POINTER(RECV)()
        size = DWORD()
        while self.handle:
            hr = self.dll.SimConnect_GetNextDispatch(self.handle, byref(p), byref(size))
            if hr < 0:
                break
            count += 1
            self._handle(p, size.value)
        return count

    def _handle(self, p, size):
        rid = p.contents.dwID
        addr = ctypes.addressof(p.contents)
        if rid == RECV_ID_SIMOBJECT_DATA:
            msg = RECV_SIMOBJECT_DATA.from_address(addr)
            if msg.dwRequestID == REQ_INPUTS:
                vals = (c_double * 2).from_address(addr + sizeof(RECV_SIMOBJECT_DATA))
                self.on_inputs(vals[0], vals[1])
        elif rid == RECV_ID_EVENT_FILENAME:
            msg = RECV_EVENT_FILENAME.from_address(addr)
            if msg.evt.uEventID == EVT_AIRCRAFT_LOADED:
                self.on_aircraft(msg.szFileName.decode("utf-8", "replace"))
        elif rid == RECV_ID_EVENT:
            msg = RECV_EVENT.from_address(addr)
            if msg.uEventID == EVT_SIM_START:
                self.request_aircraft()
        elif rid == RECV_ID_SYSTEM_STATE:
            msg = RECV_SYSTEM_STATE.from_address(addr)
            if msg.dwRequestID == REQ_AIRCRAFT:
                self.on_aircraft(msg.szString.decode("utf-8", "replace"))
        elif rid == RECV_ID_EXCEPTION:
            msg = RECV_EXCEPTION.from_address(addr)
            log.warning("SimConnect exception %d (send id %d, index %d)",
                        msg.dwException, msg.dwSendID, msg.dwIndex)
        elif rid == RECV_ID_QUIT:
            log.info("MSFS closed")
            self.close()
            self.on_quit()
