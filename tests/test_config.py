import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import config  # noqa: E402


class TestSettingsUpgrade(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "settings.json")

    def write(self, data, defaults=None):
        with open(self.path, "w") as f:
            json.dump(data, f)
        if defaults is not None:
            with open(os.path.join(self.dir, "defaults.json"), "w") as f:
                json.dump(defaults, f)

    def test_first_run_writes_files(self):
        s = config.load_settings(self.path)
        self.assertEqual(s.rest_deadband, config.Settings().rest_deadband)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "defaults.json")))

    def test_legacy_untouched_value_upgrades(self):
        self.write({"rest_deadband": 0.015, "invert_pedal": False})  # 1.0.0 test build, no defaults.json
        s = config.load_settings(self.path)
        self.assertEqual(s.rest_deadband, config.Settings().rest_deadband)

    def test_user_changed_value_kept(self):
        self.write({"rest_deadband": 0.02}, defaults={"rest_deadband": 0.015})
        self.assertEqual(config.load_settings(self.path).rest_deadband, 0.02)

    def test_new_default_upgrades_untouched(self):
        self.write({"trim_slew_rate": 0.05}, defaults={"trim_slew_rate": 0.05})
        self.assertEqual(config.load_settings(self.path).trim_slew_rate, config.Settings().trim_slew_rate)

    def test_user_value_equal_to_current_default_kept(self):
        self.write({"invert_pedal": True}, defaults={"invert_pedal": False})
        self.assertTrue(config.load_settings(self.path).invert_pedal)


if __name__ == "__main__":
    unittest.main()
