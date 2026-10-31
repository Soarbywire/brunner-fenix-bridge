"""Settings, stored as JSON in %APPDATA%\\BrunnerFenixBridge\\settings.json."""

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields

from . import APP_ID

log = logging.getLogger(__name__)


@dataclass
class Settings:
    # --- Variables -------------------------------------------------------
    # Fenix cockpit rudder pedal animation: trim + pilot input, -1000..+1000.
    fenix_rudder_lvar: str = "L:N_FC_RUDDER"
    # Published by SimUX: physical pedal position, -1..+1 (Ratio Signed).
    pedal_lvar: str = "L:BRUNNER_RAW_PEDAL"
    # Read by SimUX: where the pedals should sit for the current trim, -1..+1.
    trim_lvar: str = "L:BRUNNER_RUDDER_TRIM"

    # --- Aircraft detection ---------------------------------------------
    # The bridge is active when the loaded aircraft path contains any of these.
    aircraft_match: list = field(default_factory=lambda: ["FNX", "Fenix"])
    # True = act as if a Fenix is always loaded (for troubleshooting).
    force_active: bool = False
    # In other aircraft: True = send the pedals straight through as rudder,
    # False = send nothing (use when SimUX handles rudder in other aircraft).
    passthrough_other_aircraft: bool = False

    # --- Scaling ---------------------------------------------------------
    fenix_full_scale: float = 1000.0   # L:N_FC_RUDDER value at full pedal
    hw_scale: float = 1.0              # trim units -> pedal hardware units
    degrees_full_scale: float = 30.0   # rudder degrees at full pedal (display only)
    trim_limit: float = 0.70           # max trim magnitude accepted (20 deg = 0.667)
    # True if SimUX's pedal direction is opposite to the Fenix's (right = positive).
    # Flips both the pedal position read and the trim position sent to SimUX.
    invert_pedal: bool = False
    # MSFS's AXIS_RUDDER_SET runs opposite to the Fenix (tested: positive = left).
    # True flips the rudder sent to MSFS. Set to false if right pedal gives left rudder.
    invert_rudder_output: bool = True
    # True: SimUX reports the absolute pedal position (tested in MSFS and X-Plane).
    # False: SimUX reports the pedal relative to the trimmed position.
    pedal_includes_trim: bool = True

    # --- Trim following (pedals) -----------------------------------------
    trim_friction: float = 0.013       # breakout before pedals move (~0.4 deg)
    estimate_smooth_tau: float = 0.1   # s: smoothing on the trim estimate (removes jitter)
    still_band: float = 0.002          # trim moving less than this (~0.06 deg) counts as stopped
    settle_time: float = 0.5           # s of stillness before friction latches again
    trim_slew_rate: float = 0.10       # max pedal travel speed following trim (units/s)
    input_settle_time: float = 0.25    # s rudder input must be steady to update trim estimate
    input_steady_band: float = 0.01    # how much rudder input may wobble and still be "steady"
    estimate_input_limit: float = 0.05 # trim is only worked out while rudder input is below this
    fenix_input_gain: float = 1.0      # how much of the sent rudder shows up in N_FC_RUDDER

    # --- Pilot input (rudder) --------------------------------------------
    rest_deadband: float = 0.03        # deadband when the pedals are settled
    motion_deadband: float = 0.10      # deadband while the motor is moving the pedals
    deadband_decay: float = 0.3        # how fast motion_deadband shrinks back (per s)
    rudder_smooth_tau: float = 0.033   # rudder output smoothing (s)

    # --- App -------------------------------------------------------------
    check_updates_on_start: bool = True


def settings_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_ID)


def settings_path() -> str:
    return os.path.join(settings_dir(), "settings.json")


# Defaults written by 1.0.0 test builds, which kept no record of their defaults.
LEGACY_DEFAULTS = {"rest_deadband": 0.015}


def _defaults_path(path: str) -> str:
    return os.path.join(os.path.dirname(path), "defaults.json")


def load_settings(path: str | None = None) -> Settings:
    """Load settings. Any value the user never changed follows new defaults:
    defaults.json records the defaults last written, so a stored value equal
    to its old default is upgraded when the default changes."""
    path = path or settings_path()
    s = Settings()
    current = asdict(s)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            try:
                with open(_defaults_path(path), "r", encoding="utf-8") as f:
                    previous = json.load(f)
            except Exception:
                previous = dict(LEGACY_DEFAULTS)
            for k, v in data.items():
                if k not in current:
                    continue
                if k in previous and v == previous[k] and current[k] != previous[k]:
                    log.info("Setting %s: default changed %r -> %r", k, v, current[k])
                    continue  # user never changed it: take the new default
                setattr(s, k, v)
        except Exception:
            log.exception("Could not read settings from %s, using defaults", path)
    save_settings(s, path)  # writes any new settings back to the file
    try:
        with open(_defaults_path(path), "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception:
        log.exception("Could not save defaults record")
    return s


def save_settings(s: Settings, path: str | None = None) -> None:
    path = path or settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(s), f, indent=2)
    except Exception:
        log.exception("Could not save settings to %s", path)
