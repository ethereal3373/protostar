"""
fonts.py — loads the Inter font for Protostar only.

Inter is a free font (SIL Open Font License, see fonts/Inter-LICENSE.txt),
made by Rasmus Andersson. It's not installed in Windows: we ask Windows to
make it available to THIS program only ("private"), every time it starts.
Nothing on the rest of the PC changes.

If loading fails for any reason, we fall back to Windows' own Segoe UI.
"""

import ctypes
from pathlib import Path

FOLDER = Path(__file__).parent / "fonts"
FR_PRIVATE = 0x10          # "only for this program"
_loaded = None


def load():
    """Make Inter available. Returns (regular family, semibold family) names for Tkinter."""
    global _loaded
    if _loaded:
        return _loaded
    gdi = ctypes.WinDLL("gdi32")
    ok = True
    for file in ("Inter-Regular.ttf", "Inter-SemiBold.ttf"):
        path = FOLDER / file
        if not path.exists() or gdi.AddFontResourceExW(str(path), FR_PRIVATE, 0) == 0:
            ok = False
    _loaded = ("Inter", "Inter SemiBold") if ok else ("Segoe UI", "Segoe UI Semibold")
    return _loaded
