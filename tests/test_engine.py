import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Settings  # noqa: E402
from bridge.engine import Engine  # noqa: E402


class FakeSC:
    def __init__(self, engine):
        self.engine = engine
        self.trims, self.rudders = [], []
        self.opened = self.closed = False

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def dispatch(self):
        return 0

    def set_trim(self, v):
        self.trims.append(v)

    def set_rudder(self, v):
        self.rudders.append(v)


class TestEngine(unittest.TestCase):
    def test_rudder_output_not_inverted_when_disabled(self):
        e, sc = self.make(invert_rudder_output=False)
        try:
            e.on_aircraft("FNX_32X")
            for _ in range(30):
                e.on_inputs(0.0, 0.4)
                time.sleep(0.005)
            self.assertGreater(sc.rudders[-1], 0.3)
        finally:
            e.stop()

    def make(self, **kw):
        s = Settings(**kw)
        holder = {}

        def factory(engine):
            holder["sc"] = FakeSC(engine)
            return holder["sc"]
        e = Engine(s, simconnect_factory=factory)
        e.start()
        for _ in range(50):
            if "sc" in holder and e.snapshot().connected:
                break
            time.sleep(0.02)
        return e, holder["sc"]

    def test_fenix_detected_and_rudder_sent(self):
        e, sc = self.make()
        try:
            e.on_aircraft(r"SimObjects\Airplanes\FNX_32X\aircraft.cfg")
            for _ in range(30):
                e.on_inputs(0.0, 0.4)   # pilot pushes right, trim 0
                time.sleep(0.005)
            st = e.snapshot()
            self.assertEqual(st.mode, "Fenix")
            self.assertLess(sc.rudders[-1], -0.3, "right pedal is sent as negative AXIS_RUDDER_SET")
            self.assertAlmostEqual(sc.trims[-1], 0.0, places=3)
        finally:
            e.stop()

    def test_other_aircraft_idle_sends_no_rudder(self):
        e, sc = self.make()
        try:
            e.on_aircraft(r"SimObjects\Airplanes\Asobo_C172\aircraft.cfg")
            e.on_inputs(0.0, 0.5)
            self.assertEqual(e.snapshot().mode, "Idle")
            self.assertEqual(sc.rudders, [])
            self.assertEqual(sc.trims[-1], 0.0)
        finally:
            e.stop()

    def test_other_aircraft_passthrough(self):
        e, sc = self.make(passthrough_other_aircraft=True)
        try:
            e.on_aircraft(r"SimObjects\Airplanes\Asobo_C172\aircraft.cfg")
            e.on_inputs(0.0, 0.5)
            self.assertEqual(e.snapshot().mode, "Passthrough")
            self.assertAlmostEqual(sc.rudders[-1], -0.5)
        finally:
            e.stop()


if __name__ == "__main__":
    unittest.main()
