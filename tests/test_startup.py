import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import APP_NAME, startup  # noqa: E402

EXISTING = """<?xml version="1.0" encoding="Windows-1252"?>
<SimBase.Document Type="SimConnect" version="1,0">
  <Descr>Auto launch external applications on MSFS start</Descr>
  <Filename>exe.xml</Filename>
  <Disabled>False</Disabled>
  <Launch.ManualLoad>False</Launch.ManualLoad>
  <!-- keep this comment -->
  <Launch.Addon>
    <Name>FSUIPC7</Name>
    <Disabled>False</Disabled>
    <Path>C:\\FSUIPC7\\FSUIPC7.exe</Path>
    <CommandLine>-auto</CommandLine>
  </Launch.Addon>
</SimBase.Document>
"""

EXE = r"C:\Users\Ben\Documents\BrunnerFenixBridge\BrunnerFenixBridge.exe"


class TestExeXml(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "exe.xml")

    def names(self):
        root = ET.parse(self.path).getroot()
        return [a.findtext("Name") for a in root.findall("Launch.Addon")]

    def test_add_keeps_other_addons_and_backs_up(self):
        with open(self.path, "w", encoding="cp1252") as f:
            f.write(EXISTING)
        startup.set_msfs(True, EXE, folders=[self.dir])
        self.assertEqual(self.names(), ["FSUIPC7", APP_NAME])
        self.assertTrue(startup.msfs_enabled(folders=[self.dir]))
        self.assertTrue(os.path.exists(self.path + ".BrunnerFenixBridge.bak"))
        text = open(self.path, encoding="cp1252").read()
        self.assertIn("keep this comment", text)
        self.assertIn("<CommandLine>--auto</CommandLine>", text)
        self.assertIn(EXE, text)

    def test_add_twice_no_duplicate_and_no_rewrite(self):
        with open(self.path, "w", encoding="cp1252") as f:
            f.write(EXISTING)
        startup.set_msfs(True, EXE, folders=[self.dir])
        self.assertEqual(startup.set_msfs(True, EXE, folders=[self.dir]), [], "unchanged: no write")
        self.assertEqual(self.names().count(APP_NAME), 1)

    def test_path_refresh(self):
        startup.set_msfs(True, EXE, folders=[self.dir])
        startup.set_msfs(True, r"D:\New\BrunnerFenixBridge.exe", folders=[self.dir])
        self.assertIn(r"D:\New", open(self.path, encoding="cp1252").read())
        self.assertEqual(self.names().count(APP_NAME), 1)

    def test_remove_only_ours(self):
        with open(self.path, "w", encoding="cp1252") as f:
            f.write(EXISTING)
        startup.set_msfs(True, EXE, folders=[self.dir])
        startup.set_msfs(False, EXE, folders=[self.dir])
        self.assertEqual(self.names(), ["FSUIPC7"])
        self.assertFalse(startup.msfs_enabled(folders=[self.dir]))

    def test_create_when_missing(self):
        startup.set_msfs(True, EXE, folders=[self.dir])
        self.assertEqual(self.names(), [APP_NAME])
        root = ET.parse(self.path).getroot()
        self.assertEqual(root.tag, "SimBase.Document")
        self.assertEqual(root.findtext("Launch.ManualLoad"), "False")

    def test_broken_file_not_overwritten(self):
        with open(self.path, "w") as f:
            f.write("<SimBase.Document><oops>")
        with self.assertRaises(ET.ParseError):
            startup.set_msfs(True, EXE, folders=[self.dir])
        self.assertEqual(open(self.path).read(), "<SimBase.Document><oops>")

    def test_folder_detection(self):
        local = os.path.join(self.dir, "local")
        store = os.path.join(local, "Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache")
        os.makedirs(store)
        found = startup.msfs_folders({"LOCALAPPDATA": local, "APPDATA": os.path.join(self.dir, "none")})
        self.assertEqual(found, [store])


if __name__ == "__main__":
    unittest.main()
