"""Closed-loop tests: the bridge against a simulated Fenix and motorised pedals."""

import math
import os
import random
import sys
import unittest
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Settings  # noqa: E402
from bridge.logic import RudderBridge, format_trim  # noqa: E402

DT = 1 / 60
DEG = 1 / 30  # one degree of trim in full-pedal units


class Plant:
    """Simulated Fenix + SimUX + Brunner pedals, with latency and motor lag."""

    def __init__(self, fenix_trim=0.0, latency_frames=3, motor_tau=0.08, seed=1, fenix_tau=0.0, gain=0.8, relative=True):
        self.fenix_trim = fenix_trim
        self.axis_queue = deque([0.0] * latency_frames)   # bridge -> Fenix
        self.trim_queue = deque([0.0] * 2)                # bridge -> SimUX -> motor
        self.motor = 0.0
        self.motor_tau = motor_tau
        self.pilot = 0.0          # pilot's displacement from the motor position
        self.knob = 0             # -1 left, 0 centre, +1 right (1 deg/s)
        self.noise = random.Random(seed)
        self.axis_now = 0.0
        self.fenix_tau = fenix_tau   # Fenix smoothing of the pedal animation
        self.gain = gain             # measured: Fenix shows ~80% of the rudder sent
        self.relative = relative     # SimUX reports pedal relative to its trim (MSFS)
        self.target = 0.0

    def outputs(self):
        """What the bridge reads this frame: (N_FC_RUDDER, pedal)."""
        n = max(-1.0, min(1.0, self.fenix_trim + self.axis_now)) * 1000
        n += self.noise.uniform(-1.5, 1.5)  # small jitter, like the real readout
        absolute = max(-1.0, min(1.0, self.motor + self.pilot))
        pedal = absolute - self.target if self.relative else absolute
        return n, pedal

    def advance(self, trim_out, rudder_out, dt=DT):
        self.fenix_trim = max(-0.667, min(0.667, self.fenix_trim + self.knob * DEG * dt))
        self.axis_queue.append(rudder_out)
        a = self.axis_queue.popleft()
        k = 1 - math.exp(-dt / self.fenix_tau) if self.fenix_tau else 1.0
        self.axis_now += (a * self.gain - self.axis_now) * k
        self.trim_queue.append(trim_out)
        target = self.trim_queue.popleft()
        self.target = target
        self.motor += (target - self.motor) * (1 - math.exp(-dt / self.motor_tau))


def run(bridge, plant, seconds, each=None):
    log = []
    for i in range(int(seconds / DT)):
        if each:
            each(i * DT, plant)
        n, pedal = plant.outputs()
        r = bridge.step(DT, n, pedal)
        plant.advance(r.trim_out, r.rudder_out)
        log.append((i * DT, n, pedal, r, plant.fenix_trim + plant.axis_now))
    return log


class TestBridge(unittest.TestCase):
    ABSOLUTE = True  # SimUX pedal reading: absolute (tested) or relative to trim

    def setUp(self):
        self.s = Settings(pedal_includes_trim=self.ABSOLUTE)
        self.b = RudderBridge(self.s)

    def plant(self, **kw):
        kw.setdefault("relative", not self.ABSOLUTE)
        return Plant(**kw)

    def test_feet_off_trim_left_5(self):
        p = self.plant()

        def knob(t, pl):
            pl.knob = -1 if 1.0 <= t < 6.0 else 0
        log = run(self.b, p, 15, knob)
        t, n, pedal, r, total = log[-1]
        self.assertAlmostEqual(p.fenix_trim, -5 * DEG, places=3)
        self.assertAlmostEqual(p.motor, -5 * DEG, delta=0.01, msg="pedals sit at the trim position")
        self.assertLess(abs(r.rudder_out), 0.005, "no phantom rudder input")
        self.assertAlmostEqual(total, -5 * DEG, delta=0.01, msg="Fenix rudder = trim only (no double count)")
        self.assertEqual(format_trim(r.trim_degrees), "L 5.0")

    def test_no_runaway_over_time(self):
        p = self.plant(fenix_trim=3 * DEG)
        log = run(self.b, p, 60)
        worst = max(abs(x[4] - 3 * DEG) for x in log[int(5 / DT):])
        self.assertLess(worst, 0.01, "total rudder stays at the trim, no runaway")

    def test_full_pedal_does_not_move_trim(self):
        p = self.plant()

        def push(t, pl):
            pl.pilot = 0.0 if t < 2 else min(1.0, (t - 2) * 2)  # full right over 0.5 s
        log = run(self.b, p, 10, push)
        t, n, pedal, r, total = log[-1]
        self.assertGreater(r.rudder_out, 0.95)
        self.assertLess(abs(self.b.mech_trim), 0.01, "pedal trim position must not chase the pilot")

    def test_pilot_input_with_trim(self):
        p = self.plant()

        def seq(t, pl):
            pl.knob = -1 if 0.5 <= t < 5.5 else 0
            pl.pilot = 0.3 if t >= 12 else 0.0
        log = run(self.b, p, 25, seq)
        t, n, pedal, r, total = log[-1]
        self.assertAlmostEqual(r.rudder_out, 0.3 - self.s.rest_deadband, delta=0.01)
        self.assertAlmostEqual(self.b.mech_trim, -5 * DEG, delta=0.01, msg="trim position held while pilot pushes")
        self.assertAlmostEqual(total, -5 * DEG + p.gain * (0.3 - self.s.rest_deadband), delta=0.015)

    def test_taxi_wiggle_keeps_pedals_centred(self):
        p = self.plant()

        def wiggle(t, pl):
            pl.pilot = 0.6 * math.sin(2 * math.pi * 0.7 * t)
        log = run(self.b, p, 30, wiggle)
        worst = max(abs(x[3].trim_out) for x in log)
        self.assertLess(worst, 0.02, "pedal centre stays put while taxiing")

    def test_ap_micro_trim_ignored(self):
        p = self.plant(fenix_trim=1 * DEG)
        rng = random.Random(4)

        def micro(t, pl):
            pl.fenix_trim = 1 * DEG + rng.uniform(-0.15, 0.15) * DEG if int(t * 2) % 2 else pl.fenix_trim
        log = run(self.b, p, 40, micro)
        tail = [x[3].trim_out for x in log[int(5 / DT):]]
        self.assertLess(max(tail) - min(tail), 0.002, "pedals stay still for tiny AP tweaks")

    def test_startup_with_existing_trim(self):
        p = self.plant(fenix_trim=-3 * DEG)
        log = run(self.b, p, 10)
        t, n, pedal, r, total = log[-1]
        self.assertAlmostEqual(p.motor, -3 * DEG, delta=0.01)
        self.assertLess(abs(r.rudder_out), 0.005)
        jump = max(abs(log[i + 1][3].trim_out - log[i][3].trim_out) for i in range(len(log) - 1))
        self.assertLessEqual(jump, self.s.trim_slew_rate * DT + 1e-9, "pedals glide, never snap")

    def test_smooth_tracking_during_continuous_trim(self):
        p = self.plant()

        def knob(t, pl):
            pl.knob = 1 if 1 <= t < 11 else 0
        log = run(self.b, p, 14, knob)
        moving = [x[3].trim_out for x in log if 3 <= x[0] < 10]
        w = int(0.25 / DT)  # quarter-second windows: what you feel as cogging
        moves = [moving[i + w] - moving[i] for i in range(0, len(moving) - w, w)]
        expected = DEG * 0.25
        for m in moves:
            self.assertAlmostEqual(m, expected, delta=expected * 0.3,
                                   msg="steady movement, no stop-start cogging")

    def test_engine_failure_trim_while_holding_rudder(self):
        p = self.plant()

        def seq(t, pl):
            pl.pilot = 0.25 if 1 <= t < 12 else 0.0     # hold right rudder, then relax
            pl.knob = 1 if 3 <= t < 8 else 0             # trim R 5 while holding it
        log = run(self.b, p, 20, seq)
        held = [x[3].trim_out for x in log if 2 <= x[0] < 12]
        self.assertLess(max(held) - min(held), 0.002, "held pedal never reads as trim")
        t, n, pedal, r, total = log[-1]
        self.assertAlmostEqual(self.b.mech_trim, 5 * DEG, delta=0.01, msg="pedals go to the trim once relaxed")
        self.assertLess(abs(r.rudder_out), 0.005)
        self.assertAlmostEqual(total, 5 * DEG, delta=0.01)

    def test_held_pedal_does_not_read_as_trim(self):
        """User report: full right pedal showed trim L 5.3, full left R 3.2."""
        for push in (0.98, -0.98, 0.5, -0.5):
            b = RudderBridge(self.s)
            p = self.plant()

            def seq(t, pl, push=push):
                pl.pilot = push if t >= 2 else 0.0
            log = run(b, p, 8, seq)
            worst = max(abs(x[3].trim_degrees) for x in log)
            self.assertLess(worst, 0.3, f"pedal {push:+} must not show as trim")
            self.assertLess(abs(b.mech_trim), 0.005)

    def test_slow_laggy_fenix(self):
        p = self.plant(fenix_trim=-4 * DEG, latency_frames=8, fenix_tau=0.15)

        def seq(t, pl):
            pl.pilot = 0.5 * math.sin(2 * math.pi * 0.5 * t) if 10 <= t < 20 else 0.0
        log = run(self.b, p, 30, seq)
        t, n, pedal, r, total = log[-1]
        self.assertAlmostEqual(p.motor, -4 * DEG, delta=0.01)
        self.assertLess(abs(r.rudder_out), 0.005)
        during = [x[3].trim_out for x in log if 10 <= x[0] < 20]
        self.assertLess(max(during) - min(during), 0.02, "pedal centre steady while pilot moves")

    def test_user_report_trim_l5_feet_off(self):
        """MSFS test: trim L 5, pedals settled at -0.1631 (absolute), N_FC_RUDDER -168."""
        if not self.ABSOLUTE:
            self.skipTest("absolute-reading case")
        b = RudderBridge(self.s)
        for _ in range(int(10 / DT)):
            r = b.step(DT, -168.0, -0.1631)
        self.assertEqual(format_trim(r.trim_degrees), "L 5.0")
        self.assertAlmostEqual(r.trim_out, -0.168, delta=0.002)
        self.assertEqual(r.rudder_out, 0.0, "settled pedals must not read as rudder")

    def test_start_while_holding_pedal(self):
        b = RudderBridge(self.s)
        for _ in range(int(3 / DT)):
            r = b.step(DT, 0.0, 0.4)  # pilot holding right pedal as the bridge starts
        self.assertLess(abs(b.mech_trim), 0.005, "held pedal is not taken as trim")
        self.assertGreater(r.rudder_out, 0.3)

    def test_invert_pedal(self):
        self.s.invert_pedal = True
        b = RudderBridge(self.s)
        p = self.plant(fenix_trim=2 * DEG)
        # SimUX's pedal sign is opposite: wrap the plant so pedal reads and trim writes flip.
        for _ in range(int(10 / DT)):
            n, pedal = p.outputs()
            r = b.step(DT, n, -pedal)
            p.advance(-r.trim_out, r.rudder_out)
        self.assertAlmostEqual(p.motor, 2 * DEG, delta=0.01)
        self.assertLess(abs(r.rudder_out), 0.005)


class TestBridgeRelativePedal(TestBridge):
    """Same checks with SimUX reporting the pedal relative to the trimmed position."""
    ABSOLUTE = False


class TestFormat(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_trim(0.01), "0.0")
        self.assertEqual(format_trim(-5.04), "L 5.0")
        self.assertEqual(format_trim(1.25), "R 1.2")


if __name__ == "__main__":
    unittest.main()
