"""
startup.py — make Protostar start by itself when you log in to Windows.

    python startup.py install   -> start Protostar at every login (and start it now)
    python startup.py remove    -> stop starting it at login

How it works
------------
Windows has a special "Startup" folder. Every shortcut in it is opened
automatically when you log in. We put a shortcut to Protostar there.

The shortcut runs Protostar with `pythonw.exe` instead of `python.exe`.
They are the same Python, but pythonw ("w" for window) runs WITHOUT a
terminal window, so Protostar stays invisible until you press Ctrl+Alt+I.
"""

import os
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent / "protostar.py"
STARTUP_FOLDER = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
SHORTCUT = STARTUP_FOLDER / "Protostar.lnk"  # .lnk = a Windows shortcut file

# pythonw.exe lives in the same folder as the python.exe running this script.
PYTHONW = Path(sys.executable).with_name("pythonw.exe")


def install():
    if not PYTHONW.exists():
        sys.exit(f"Could not find {PYTHONW}")

    # Python can't make Windows shortcuts by itself, so we ask PowerShell to,
    # using a built-in Windows helper called "WScript.Shell".
    script = f"""
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut('{SHORTCUT}')
        $s.TargetPath = '{PYTHONW}'
        $s.Arguments = '"{APP}"'
        $s.WorkingDirectory = '{APP.parent}'
        $s.Description = 'Protostar - quick idea capture'
        $s.Save()
    """
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    print(f"Installed: {SHORTCUT}")

    # Start it right away too, so you don't have to log out and back in.
    # Popen starts it and doesn't wait for it to finish.
    subprocess.Popen([PYTHONW, APP], cwd=APP.parent)
    print("Protostar is now running in the background. Ctrl+Alt+I = new idea.")


def remove():
    if SHORTCUT.exists():
        SHORTCUT.unlink()  # delete the shortcut file
        print(f"Removed: {SHORTCUT}")
    else:
        print("Protostar was not set to start at login.")
    print("If it's running right now, press Ctrl+Alt+Q to stop it.")


if __name__ == "__main__":
    # sys.argv is the list of words typed after "python":
    # ["startup.py", "install"] -> sys.argv[1] is "install"
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "install":
        install()
    elif command == "remove":
        remove()
    else:
        print(__doc__)
