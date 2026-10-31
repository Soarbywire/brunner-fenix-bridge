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


class TestInstall(unittest.TestCase):
    def test_swap_and_restart(self):
        import tempfile
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "BrunnerFenixBridge.exe")
        new = os.path.join(d, "BrunnerFenixBridge.new.exe")
        open(exe, "w").write("old version")
        open(new, "w").write("new version")
        with mock.patch.object(updater.sys, "executable", exe), \
             mock.patch.object(updater.subprocess, "Popen") as popen:
            updater.install_and_restart(new)
        self.assertEqual(open(exe).read(), "new version")
        self.assertEqual(open(exe + ".old").read(), "old version")
        self.assertFalse(os.path.exists(new))
        popen.assert_called_once()
        self.assertEqual(popen.call_args[0][0], [exe, updater.UPDATED_ARG])

        with mock.patch.object(updater.sys, "executable", exe), \
             mock.patch.object(updater, "can_self_update", return_value=True):
            updater.cleanup_old()
        self.assertFalse(os.path.exists(exe + ".old"))

    def test_failed_swap_restores_running_exe(self):
        import tempfile
        d = tempfile.mkdtemp()
        exe = os.path.join(d, "BrunnerFenixBridge.exe")
        open(exe, "w").write("old version")
        with mock.patch.object(updater.sys, "executable", exe), \
             mock.patch.object(updater.subprocess, "Popen"):
            with self.assertRaises(Exception):
                updater.install_and_restart(os.path.join(d, "missing.exe"))
        self.assertEqual(open(exe).read(), "old version")


if __name__ == "__main__":
    unittest.main()
