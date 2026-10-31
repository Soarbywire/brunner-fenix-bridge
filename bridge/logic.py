"""Core control logic. Pure Python with no SimConnect, so it can be unit tested.

The Fenix animates its cockpit rudder pedals with L:N_FC_RUDDER, which holds
trim + pilot rudder input (about -1000..+1000). The physical Brunner pedals
should sit at the trim position, and the pilot's input must be sent to the
Fenix relative to that position. So each frame:

    trim estimate  = N_FC_RUDDER / full_scale - rudder input we sent
    pedal target   = trim estimate (filtered)        -> SimUX via L:var
    rudder to sim  = physical pedal - pedal target   -> AXIS_RUDDER_SET

The trim estimate is only updated while our rudder output has been steady
for a short time, so the Fenix's processing lag never reads as a trim change.
"""

import math
from dataclasses import dataclass

from .config import Settings


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass
class StepResult:
    trim_out: float          # to SimUX: pedal position for the current trim (-1..1, pedal sign)
    rudder_out: float        # to MSFS: pilot rudder input relative to trim (-1..1)
    trim_estimate: float     # Fenix trim, full-pedal units (-1..1)
    trim_degrees: float      # same, in degrees (display)
    pedal: float             # physical pedal position as read
    deadband: float          # current input deadband
    estimate_valid: bool     # trim estimate updated this frame


class RudderBridge:
    def __init__(self, settings: Settings):
        self.s = settings
        self.reset()

    def reset(self) -> None:
        self.initialised = False
        self.trim_estimate = 0.0
        self.committed_trim = 0.0
        self.mech_trim = 0.0
        self.est_filtered = 0.0
        self.still_anchor = 0.0
        self.tracking = False
        self.still_time = 0.0
        self.deadband = self.s.rest_deadband
        self.rudder_smooth = 0.0
        self.last_rudder_sent = 0.0
        self.steady_ref = 0.0
        self.steady_time = 0.0
        self.last_estimate_raw = 0.0

    # ------------------------------------------------------------------
    def step(self, dt: float, fenix_rudder: float, pedal: float) -> StepResult:
        s = self.s
        if dt <= 0:
            dt = 1e-3
        dt = min(dt, 0.1)  # pauses and loading stutters

        if s.invert_pedal:
            pedal = -pedal
        n = fenix_rudder / s.fenix_full_scale if s.fenix_full_scale else 0.0

        # --- 1. Trim estimate, gated on steady rudder output ---------------
        if abs(self.last_rudder_sent - self.steady_ref) > s.input_steady_band:
            self.steady_ref = self.last_rudder_sent
            self.steady_time = 0.0
        else:
            self.steady_time += dt

        estimate_valid = False
        # Only while the pilot's input is small: the Fenix doesn't pass rudder
        # input through 1:1, so a held pedal would otherwise read as trim.
        if (self.steady_time >= s.input_settle_time and abs(n) < 0.95
                and abs(self.last_rudder_sent) <= s.estimate_input_limit):
            raw = clamp(n - s.fenix_input_gain * self.last_rudder_sent,
                        -s.trim_limit, s.trim_limit)
            self.trim_estimate = raw
            estimate_valid = True

        if not self.initialised:
            # Start from where the pedals physically are (they may already be
            # trimmed, e.g. after restarting the bridge) and glide from there.
            # Only when the physical pedals agree with the Fenix's cockpit pedals;
            # otherwise the pilot may be holding a pedal, so start centred.
            start = 0.0
            if s.pedal_includes_trim and s.hw_scale:
                physical = pedal / s.hw_scale
                if abs(physical - n) < 0.05:
                    start = clamp(physical, -s.trim_limit, s.trim_limit)
            self.est_filtered = self.trim_estimate
            self.still_anchor = self.trim_estimate
            self.committed_trim = start
            self.mech_trim = start
            self.initialised = True
        else:
            a = 1.0 - math.exp(-dt / s.estimate_smooth_tau) if s.estimate_smooth_tau > 0 else 1.0
            self.est_filtered += (self.trim_estimate - self.est_filtered) * a
        est = self.est_filtered

        # --- 2. Breakout friction with tracking ----------------------------
        # Small changes are ignored. Once the trim breaks out, the pedals follow
        # it continuously until it has been still for settle_time.
        if abs(est - self.still_anchor) > s.still_band:
            self.still_anchor = est
            self.still_time = 0.0
        else:
            self.still_time += dt

        if self.tracking:
            self.committed_trim = est
            if self.still_time >= s.settle_time:
                self.tracking = False
        elif abs(est - self.committed_trim) > s.trim_friction:
            self.tracking = True
            self.committed_trim = est

        # --- 3. Slew limit: pedals glide, never snap ------------------------
        step = s.trim_slew_rate * dt
        move = clamp(self.committed_trim - self.mech_trim, -step, step)
        moving = abs(move) > 1e-6
        self.mech_trim += move
        trim_out = clamp(self.mech_trim * s.hw_scale, -1.0, 1.0)

        # --- 4. Deadband: wide while the motor moves, then shrink ----------
        if moving:
            self.deadband = s.motion_deadband
        else:
            self.deadband = max(s.rest_deadband, self.deadband - s.deadband_decay * dt)

        # --- 5. Pilot input relative to the trimmed pedal position ---------
        # SimUX in MSFS reports the pedal relative to its trim position already;
        # in X-Plane it reported the absolute position.
        diff = pedal - trim_out if s.pedal_includes_trim else pedal
        if diff > self.deadband:
            diff -= self.deadband
        elif diff < -self.deadband:
            diff += self.deadband
        else:
            diff = 0.0
        rudder = clamp(diff / s.hw_scale if s.hw_scale else diff, -1.0, 1.0)

        alpha = 1.0 - math.exp(-dt / s.rudder_smooth_tau) if s.rudder_smooth_tau > 0 else 1.0
        self.rudder_smooth += (rudder - self.rudder_smooth) * alpha
        if abs(self.rudder_smooth) < 1e-5:
            self.rudder_smooth = 0.0
        self.last_rudder_sent = self.rudder_smooth

        return StepResult(
            trim_out=-trim_out if s.invert_pedal else trim_out,
            rudder_out=self.rudder_smooth,
            trim_estimate=self.trim_estimate,
            trim_degrees=self.trim_estimate * s.degrees_full_scale,
            pedal=pedal,
            deadband=self.deadband,
            estimate_valid=estimate_valid,
        )

    def passthrough(self, pedal: float) -> StepResult:
        """Other aircraft: pedals straight through as rudder, trim centred."""
        s = self.s
        if s.invert_pedal:
            pedal = -pedal
        rudder = clamp(pedal, -1.0, 1.0)
        self.reset()
        return StepResult(0.0, rudder, 0.0, 0.0, pedal, 0.0, False)


def format_trim(degrees: float) -> str:
    """Format like the A320 trim display: 'L 5.0', 'R 1.2', '0.0'."""
    if abs(degrees) < 0.05:
        return "0.0"
    return f"{'L' if degrees < 0 else 'R'} {abs(degrees):.1f}"
