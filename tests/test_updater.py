import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import updater  # noqa: E402


class TestVersions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.4"), (1, 4, 0))
        self.assertEqual(updater.parse_version("v2"), (2, 0, 0))

    def test_newer(self):
        self.assertTrue(updater.is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(updater.is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(updater.is_newer("v0.9.0", "1.0.0"))


class TestCheck(unittest.TestCase):
    def _release(self, tag):
        return json.dumps({
            "tag_name": tag, "body": "notes", "html_url": "https://example/rel",
            "assets": [
                {"name": "BrunnerFenixBridge.exe", "browser_download_url": "https://example/exe", "size": 123},
                {"name": "BrunnerFenixBridge.exe.sha256", "browser_download_url": "https://example/sha"},
            ]}).encode()

    def test_update_found(self):
        with mock.patch.object(updater, "_get", return_value=self._release("v9.0.0")):
            info = updater.check_for_update()
        self.assertEqual(info.version, "9.0.0")
        self.assertEqual(info.exe_url, "https://example/exe")
        self.assertEqual(info.sha256_url, "https://example/sha")

    def test_no_update(self):
        with mock.patch.object(updater, "_get", return_value=self._release("v0.0.1")):
            self.assertIsNone(updater.check_for_update())


if __name__ == "__main__":
    unittest.main()
