"""
hotkey.py — listens for Protostar's global keyboard shortcuts.

"Global" means the shortcut works no matter which app is in front.

How it stays at ~0% CPU:
We don't check the keyboard over and over (that's called "polling" and
it wastes CPU). Instead we ask Windows: "please tell me when this key
combination is pressed", and then we wait. While we wait, Windows keeps
our program asleep, so it uses no CPU at all.

We talk to Windows directly with `ctypes`, which is built into Python.
It lets Python call functions inside Windows' own system files (DLLs),
so we don't need to install anything extra.
"""

import ctypes
from ctypes import wintypes

# user32.dll is the part of Windows that handles windows, mouse and keyboard.
user32 = ctypes.WinDLL("user32", use_last_error=True)

# --- Numbers Windows uses to describe keys (from Microsoft's docs) ---
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000  # holding the keys down won't fire it again and again

VK_I = 0x49  # the letter I ("I" for idea)
VK_M = 0x4D  # the letter M ("M" for map)
VK_Q = 0x51  # the letter Q

WM_HOTKEY = 0x0312  # the "message" Windows sends us when a shortcut is pressed

# Our shortcuts. Each needs an ID number we choose, so we can tell them apart.
# (We first tried Ctrl+Alt+Space, but another app on this PC already owns it.)
CAPTURE_ID = 1  # Ctrl + Alt + I -> open the capture note
QUIT_ID = 2     # Ctrl + Alt + Q -> stop Protostar
MAP_ID = 3      # Ctrl + Alt + M -> open the galaxy map


def register(hotkey_id, modifiers, key):
    """Ask Windows to tell us when this key combination is pressed."""
    ok = user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, key)
    if not ok:
        # Most common reason: another app is already using this shortcut.
        raise OSError(f"Could not register shortcut {hotkey_id}. Maybe Protostar "
                      f"is already running, or another app uses this shortcut. "
                      f"(Windows error code: {ctypes.get_last_error()})")


def listen(on_capture, on_map=None, capture_key=None, map_key=None):
    """
    Wait for shortcuts, forever, until Ctrl+Alt+Q is pressed.
    `on_capture` is a function we call every time Ctrl+Alt+I is pressed.
    `on_map` (optional) is called every time Ctrl+Alt+M is pressed.
    """
    msg = wintypes.MSG()  # an empty "envelope" that Windows fills in for us
    try:
        # The capture and map shortcuts can be changed in Settings: they arrive
        # here as (modifier keys, key). Ctrl+Alt+Q always quits.
        register(CAPTURE_ID, *(capture_key or (MOD_CONTROL | MOD_ALT, VK_I)))
        register(QUIT_ID, MOD_CONTROL | MOD_ALT, VK_Q)
        if on_map:
            register(MAP_ID, *(map_key or (MOD_CONTROL | MOD_ALT, VK_M)))

        # GetMessageW SLEEPS until Windows has a message for us.
        # This line is the reason we use ~0% CPU while idle.
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == CAPTURE_ID:
                    on_capture()
                elif msg.wParam == MAP_ID:
                    on_map()
                elif msg.wParam == QUIT_ID:
                    break
    finally:
        # Always give the shortcuts back to Windows when we stop
        # (even if registering one of them failed halfway).
        for hotkey_id in (CAPTURE_ID, QUIT_ID, MAP_ID):
            user32.UnregisterHotKey(None, hotkey_id)


# This part runs only when you start this file directly:  python hotkey.py
if __name__ == "__main__":
    print("Protostar is listening.")
    print("  Ctrl+Alt+I -> test the shortcut")
    print("  Ctrl+Alt+Q -> quit")
    listen(lambda: print("Shortcut pressed!"))
    print("Bye!")
