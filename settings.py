"""
settings.py — the choices each person can make (Settings in the app).

They're saved in ideas/settings.json, next to your ideas (so, like your
ideas, they never go to GitHub). Every option has a sensible default, so
the file can be missing or incomplete.
"""

import json
from pathlib import Path

FILE = Path(__file__).parent / "ideas" / "settings.json"

DEFAULTS = {
    "theme": "midnight",          # colours of the panels
    "accent": "blue",             # the highlight colour
    "font": "inter",              # inter / segoe
    "detail": "normal",           # galaxy detail: low / normal / high
    "animations": True,           # smooth camera flights and the star-birth flash
    "star_colours": "natural",    # natural / tags (stars take their first #tag's colour)
    "capture_save": "enter",      # enter (Shift+Enter = new line) / ctrl_enter (Enter = new line)
    "capture_hotkey": "ctrl_alt_i",
    "map_hotkey": "ctrl_alt_m",
}

# --- Themes: the colours of the panels (the galaxy itself is always space-black) ---
THEMES = {
    "midnight": {"name": "Midnight", "sidebar": "#13161c", "topbar": "#0f1217", "edge": "#222833",
                 "hover": "#1b2029", "selected": "#242b37", "input": "#1a1f28", "input_edge": "#2a3140",
                 "text": "#e7eaf0", "soft": "#aeb6c4", "dim": "#6f7889", "card": "#10141a",
                 "card_edge": "#2a3140"},
    "graphite": {"name": "Graphite", "sidebar": "#161616", "topbar": "#111111", "edge": "#262626",
                 "hover": "#1f1f1f", "selected": "#2a2a2a", "input": "#1d1d1d", "input_edge": "#2f2f2f",
                 "text": "#ececec", "soft": "#b4b4b4", "dim": "#777777", "card": "#121212",
                 "card_edge": "#2f2f2f"},
    "warm": {"name": "Warm", "sidebar": "#1f1e1d", "topbar": "#1a1918", "edge": "#2f2e2b",
             "hover": "#2a2927", "selected": "#34332f", "input": "#2a2927", "input_edge": "#3a3935",
             "text": "#eeede9", "soft": "#bdbbb3", "dim": "#83817a", "card": "#181716",
             "card_edge": "#3a3935"},
    "daylight": {"name": "Daylight", "sidebar": "#f4f5f8", "topbar": "#e9ebf0", "edge": "#d8dce4",
                 "hover": "#e6e9ef", "selected": "#dde2ec", "input": "#ffffff", "input_edge": "#cfd5df",
                 "text": "#1c2230", "soft": "#424b5c", "dim": "#7b8496", "card": "#10141a",
                 "card_edge": "#2a3140"},
}

ACCENTS = {
    "blue": {"name": "Star blue", "colour": "#7fa7e0", "focus": "#3f5f8f", "growing": "#1d2d45"},
    "teal": {"name": "Teal", "colour": "#5fc3b4", "focus": "#2f6f66", "growing": "#173733"},
    "violet": {"name": "Violet", "colour": "#a99be8", "focus": "#5a4f94", "growing": "#2a2547"},
    "amber": {"name": "Amber", "colour": "#e0a85f", "focus": "#8a6230", "growing": "#3a2b17"},
}

# Galaxy detail: how many points of light each idea brings (fewer = lighter for older PCs).
DETAIL = {"low": {"name": "Low", "gas": 160, "disc": 50},
          "normal": {"name": "Normal", "gas": 480, "disc": 150},
          "high": {"name": "High", "gas": 960, "disc": 300}}

# Shortcut choices: (name, modifier keys, key code). Modifiers: 1 = Alt, 2 = Ctrl, 4 = Shift.
HOTKEYS = {
    "ctrl_alt_i": ("Ctrl+Alt+I", 3, 0x49),
    "ctrl_alt_n": ("Ctrl+Alt+N", 3, 0x4E),
    "ctrl_shift_space": ("Ctrl+Shift+Space", 6, 0x20),
    "alt_shift_n": ("Alt+Shift+N", 5, 0x4E),
    "ctrl_alt_m": ("Ctrl+Alt+M", 3, 0x4D),
    "ctrl_alt_g": ("Ctrl+Alt+G", 3, 0x47),
    "alt_shift_m": ("Alt+Shift+M", 5, 0x4D),
}
CAPTURE_HOTKEYS = ["ctrl_alt_i", "ctrl_alt_n", "ctrl_shift_space", "alt_shift_n"]
MAP_HOTKEYS = ["ctrl_alt_m", "ctrl_alt_g", "alt_shift_m"]


def hotkey_spec(value, fallback="ctrl_alt_i"):
    """
    A shortcut as (name, modifier keys, key code), whether it was picked from
    the list above (a name like "ctrl_alt_i") or recorded by the user (saved
    as {"name": "Ctrl+Shift+K", "mods": 6, "vk": 75}).
    """
    if isinstance(value, dict) and {"name", "mods", "vk"} <= value.keys():
        return value["name"], int(value["mods"]), int(value["vk"])
    return HOTKEYS.get(value) or HOTKEYS[fallback]


WINDOW_FILE = FILE.parent / "window.json"


def load_window():
    """How the main window looked when it was last closed (None the very first time)."""
    try:
        with open(WINDOW_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_window(state):
    WINDOW_FILE.parent.mkdir(exist_ok=True)
    with open(WINDOW_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load():
    """The current settings (defaults for anything not saved yet)."""
    values = dict(DEFAULTS)
    try:
        with open(FILE, encoding="utf-8") as f:
            values.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return values


def save(values):
    FILE.parent.mkdir(exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2)


def theme(values=None):
    """The colours to use, combining the theme and the accent."""
    values = values or load()
    colours = dict(THEMES.get(values["theme"], THEMES["midnight"]))
    accent = ACCENTS.get(values["accent"], ACCENTS["blue"])
    colours.update(accent=accent["colour"], focus=accent["focus"], growing=accent["growing"])
    return colours
