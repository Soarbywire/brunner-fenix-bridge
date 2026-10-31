"""Write version_info.txt for PyInstaller (product name, version, publisher in the exe)."""
import os
import re
import sys

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
text = open(os.path.join(here, "bridge", "version.py"), encoding="utf-8").read()
version = re.search(r'"([^"]+)"', text).group(1)
nums = [int(n) for n in re.findall(r"\d+", version)[:3]]
nums += [0] * (4 - len(nums))
t = tuple(nums)

out = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Soarbywire'),
      StringStruct('FileDescription', 'Brunner Fenix Bridge - rudder pedal trim for the Fenix A320'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'BrunnerFenixBridge'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Soarbywire. MIT License.'),
      StringStruct('OriginalFilename', 'BrunnerFenixBridge.exe'),
      StringStruct('ProductName', 'Brunner Fenix Bridge'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "version_info.txt")
open(path, "w", encoding="utf-8").write(out)
print(f"Wrote {path} for version {version}")
