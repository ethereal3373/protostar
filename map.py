"""
map.py — the main Protostar app: your ideas as a 3D galaxy.

Run it with:   python map.py        (or press Ctrl+Alt+M while Protostar runs)
               python map.py demo   (a demo galaxy with 20 sample ideas, see demo.py)
(For testing you can give it another ideas file:  python map.py some_file.jsonl)

Layout
------
  Left:    your ideas in folders by month. Click a folder to open/close it.
           Click an idea to open it: its text, notes, linked ideas, and
           buttons to edit, link or delete it.
  Top:     the idea count, "Overview", and "Timeline".
  Middle:  the galaxy (move around like in Roblox Studio — see README).
           Linked ideas are joined by faint lines: constellations.
  Right:   search through all your ideas and notes.

This is a SEPARATE program from protostar.py: it only runs while it's
open, so it adds nothing to the always-running part. And it only uses
CPU while something moves: when you don't touch it, it sleeps.
"""

import ctypes
import json
import math
import subprocess
import os
import random
import sys
import time
import tkinter as tk
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

import numpy as np

import autoformat
import reminders
import fonts
import galaxy3d as g3d
import galaxy_gl
import settings
import startup
import widgets
from widgets import ScrollArea
from ideas_store import TAG, TRASH_DAYS, Store
# Reuse the same file location and window title as the always-running part.
from protostar import IDEAS_FILE, MAP_TITLE

# --- Colours: from the chosen theme and accent (Settings; see settings.py) ---
SETTINGS = settings.load()
_T = settings.theme(SETTINGS)
SIDEBAR_BG = _T["sidebar"]
PANEL_BG = _T["sidebar"]
TOPBAR_BG = _T["topbar"]
EDGE = _T["edge"]          # thin lines between areas
ROW_HOVER = _T["hover"]
ROW_SELECTED = _T["selected"]
INPUT_BG = _T["input"]
INPUT_EDGE = _T["input_edge"]
TEXT = _T["text"]
SOFT_TEXT = _T["soft"]
DIM_TEXT = _T["dim"]
ACCENT = _T["accent"]      # the highlight colour, used sparingly
DANGER = "#e0786c"         # delete stays red
GOLD = "#d9b56c"           # "done" ideas
CARD_BG = _T["card"]       # floating cards over the galaxy (hover label, stats)
CARD_EDGE = _T["card_edge"]
FOCUS_EDGE = _T["focus"]   # the outline of the text box you're typing in
CARD_TEXT = "#e7eaf0"      # text on cards over the (always dark) galaxy
LIGHT_THEME = SETTINGS["theme"] == "daylight"
# The font: Inter (free, close to the Claude app's look), loaded just for
# Protostar by fonts.py — or Windows' own Segoe UI, if chosen in Settings.
FONT, FONT_BOLD = fonts.load() if SETTINGS["font"] == "inter" else ("Segoe UI", "Segoe UI Semibold")
# Galaxy detail: fewer points of light per idea on "Low", for older PCs.
g3d.PARTICLES_PER_IDEA = settings.DETAIL[SETTINGS["detail"]]["gas"]
g3d.DISC_PER_IDEA = settings.DETAIL[SETTINGS["detail"]]["disc"]

# Life stages of an idea (see "stage" in ideas_store.py), and how its star looks:
#   spark   = a new idea: a normal star in its own colour
#   growing = you're working on it: a bigger star
#   done    = it happened: a golden star
STAGE_NAMES = {"spark": "Spark", "growing": "Growing", "done": "Done"}
STAGE_TINT = {"done": (255, 212, 130)}
STAGE_SCALE = {"spark": 1.0, "growing": 1.4, "done": 1.25}
STAGE_MARK = {"growing": "✦", "done": "★"}
TAGS_TIP = ("Type to search your ideas.\n\nTip: write #words in an idea or a\n"
            "note (like #travel) to group ideas\nwith tags. They'll show up here.")

# Soft colours for constellations and tags (cool, calm tones that suit the dark theme).
SOFT_COLOURS = [(126, 167, 224), (104, 190, 180), (160, 150, 222), (214, 182, 130),
                (150, 192, 140), (214, 146, 150)]
STAGE_PILL = {"spark": (ROW_SELECTED, TEXT), "growing": (_T["growing"], ACCENT), "done": ("#332b1a", GOLD)}
def apply_look(values):
    """
    Switch the colours, font and galaxy detail while the app is running
    (used by the live preview in Settings). These are "global" variables:
    names every part of this file reads, so changing them here changes
    them everywhere the next time something is drawn.
    """
    global _T, SIDEBAR_BG, PANEL_BG, TOPBAR_BG, EDGE, ROW_HOVER, ROW_SELECTED, INPUT_BG, INPUT_EDGE
    global TEXT, SOFT_TEXT, DIM_TEXT, ACCENT, CARD_BG, CARD_EDGE, FOCUS_EDGE, LIGHT_THEME
    global FONT, FONT_BOLD, STAGE_PILL
    _T = settings.theme(values)
    SIDEBAR_BG = PANEL_BG = _T["sidebar"]
    TOPBAR_BG, EDGE, ROW_HOVER, ROW_SELECTED = _T["topbar"], _T["edge"], _T["hover"], _T["selected"]
    INPUT_BG, INPUT_EDGE = _T["input"], _T["input_edge"]
    TEXT, SOFT_TEXT, DIM_TEXT, ACCENT = _T["text"], _T["soft"], _T["dim"], _T["accent"]
    CARD_BG, CARD_EDGE, FOCUS_EDGE = _T["card"], _T["card_edge"], _T["focus"]
    LIGHT_THEME = values["theme"] == "daylight"
    FONT, FONT_BOLD = fonts.load() if values["font"] == "inter" else ("Segoe UI", "Segoe UI Semibold")
    STAGE_PILL = {"spark": (ROW_SELECTED, TEXT), "growing": (_T["growing"], ACCENT), "done": ("#332b1a", GOLD)}
    g3d.PARTICLES_PER_IDEA = settings.DETAIL[values["detail"]]["gas"]
    g3d.DISC_PER_IDEA = settings.DETAIL[values["detail"]]["disc"]


CLUSTER_SPACING = 0.03     # how close linked ideas sit to each other (tried 0.02-0.05)
SIDEBAR_WIDTH = 290
PANEL_WIDTH = 300
CHECK_EVERY_MS = 1000      # how often to look for ideas saved by the capture note


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def title_and_text(idea):
    """
    Return (title, text) for an idea. Ideas saved before titles existed only
    have "text", so we use their first line as the title.
    """
    if "title" in idea:
        return idea["title"], idea["text"]
    title, _, text = idea["text"].partition("\n")
    return title, text


def file_stamp(path):
    """A cheap "fingerprint" of the file (time changed + size), to notice changes."""
    try:
        info = path.stat()
        return (info.st_mtime_ns, info.st_size)
    except FileNotFoundError:
        return None


def colour_index(idea):
    """
    Which star colour an idea gets. crc32 turns text into a number that's
    always the same for the same text, so colours never change.
    """
    return zlib.crc32(idea["created"].encode()) % len(g3d.STAR_COLOURS)


def dictate(field):
    """
    Start Windows' own voice typing (the same as pressing Win+H) in `field`:
    speak, and the words are typed into the box. The speech recognition is
    done by Windows, not by Protostar (Protostar has no AI inside).
    """
    field.focus_force()
    field.after(150, lambda: _press_keys(0x5B, 0x48))     # Win + H


def _press_keys(*keys):
    user32 = ctypes.WinDLL("user32")
    for key in keys:
        user32.keybd_event(key, 0, 0, 0)
    for key in reversed(keys):
        user32.keybd_event(key, 0, 2, 0)


def soft_colour(text):
    """A soft colour that always stays the same for the same text (a tag, a group)."""
    return SOFT_COLOURS[zlib.crc32(text.encode()) % len(SOFT_COLOURS)]


def hex_colour(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


def glow_from_activity(when):
    """
    How brightly an idea shines, from the last time something happened to
    it: 1.0 if it's busy right now, slowly fading to 0.45 if it's been left
    alone for a few months. (e^(-days/30): every month it loses about 2/3
    of its extra brightness.)
    """
    days = (datetime.now() - datetime.fromisoformat(when)).total_seconds() / 86400
    return 0.45 + 0.55 * math.exp(-max(0.0, days) / 30)


def rounded_rectangle(canvas, x1, y1, x2, y2, radius, **options):
    """A rectangle with round corners (a polygon that Tkinter smooths into curves)."""
    r = radius
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, x1, y1]
    return canvas.create_polygon(points, smooth=True, **options)


def dark_title_bar(window):
    """Ask Windows to draw this window's title bar dark."""
    window.update_idletasks()
    hwnd = int(window.wm_frame(), 16)
    on = ctypes.c_int(1)
    ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))


def small_button(parent, text, command, colour=None, bg=None):
    """A little text button (like a link) that brightens when hovered."""
    # (Colours are looked up now, not when Python read this file, so a theme
    # switched in Settings is used straight away.)
    return widgets.small_button(parent, text, command, colour or DIM_TEXT, bg or SIDEBAR_BG,
                                (FONT, 9), TEXT)


def text_input(parent, value="", height=None, font_size=10, bg=None):
    """
    A dark text field with rounded corners: one line, or several if `height`
    is given. Use `box.field` to read it (box.field.get()) or bind keys to it.
    """
    box = widgets.RoundedBox(parent, bg or SIDEBAR_BG, fill=INPUT_BG, outline=INPUT_EDGE, focus_outline=FOCUS_EDGE,
                             kind="text" if height else "entry", lines=height or 1,
                             fg=TEXT, insertbackground=TEXT, font=(FONT, font_size),
                             selectbackground=ROW_SELECTED)
    if height:
        box.field.insert("1.0", value)
    else:
        box.field.insert(0, value)
    return box


def row(parent, on_click=None, selected=False, height=30, bg=None):
    """A clickable row with a rounded highlight (see widgets.Row)."""
    return widgets.Row(parent, bg or SIDEBAR_BG, on_click, height=height, hover=ROW_HOVER,
                       selected_colour=ROW_SELECTED, selected=selected)


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------

class ProtostarApp:
    def __init__(self, path):
        self.store = Store(path)
        self.store.daily_backup()     # one safety copy per day, in ideas/backups/
        self.stamp = file_stamp(path)

        self.root = tk.Tk()
        self.root.title(MAP_TITLE)
        self.root.configure(bg=SIDEBAR_BG)
        w, h = 1400, 860
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        # Open the way the window was last time: maximised, or the same size
        # and place. The very first time: maximised (full screen).
        last = settings.load_window()
        self.root.geometry(last["geometry"] if last and last.get("geometry") else f"{w}x{h}+{x}+{y}")
        self.root.minsize(960, 580)
        dark_title_bar(self.root)
        if last is None or last.get("maximised"):
            self.root.state("zoomed")         # "zoomed" is Tkinter's word for maximised
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.root.bind("<Configure>", self.remember_size, add="+")

        # Ideas are tracked by their name tag ("created" time), not by their
        # position in a list: positions change when something is deleted.
        self.selected = None          # name tag of the selected idea
        self.open_ideas = set()       # ideas opened in the sidebar
        self.closed_months = set()    # month folders the user closed
        self.opened_months = set()    # month folders the user opened
        self.editing = None           # idea being edited in the sidebar
        self.editing_note = None      # note being edited
        self.linking = None           # idea waiting for its link partner
        self.hovered = None           # scene number of the star under the mouse
        self.timeline = None          # None, or how many ideas the timeline shows
        self.trash_open = False       # the Trash folder starts closed
        self.matches = None           # while searching: the ideas that match (they light up)
        self.birth = None             # (idea, start time) while a new star is being born
        self.stats_panel = None
        self.calendar_panel = None
        self.editing_due = None       # idea whose deadline is being edited

        # Camera state (see galaxy3d.Camera). `camera` is what we draw; `goal`
        # is where your mouse and keys say it should be: each frame `camera`
        # glides part of the way there. That's what makes movement smooth.
        self.camera = g3d.Camera()
        self.goal = g3d.Camera()
        self.pivot = np.zeros(3)      # the point that left-drag circles around
        self.glide = 12.0             # how quickly the camera catches up
        self.fitted = False
        self.keys = set()
        self.anim = None
        self.last_tick = 0.0
        self.sharp_pending = None
        self.dragged = False
        self.mode = "orbit"
        self.screen = np.zeros((0, 2))
        self.visible = np.zeros(0, bool)
        self.playing = None

        self.build_sidebar()
        self.build_search_panel()
        self.build_middle()
        self.build_scene()
        self.fill_sidebar()
        self.update_topbar()
        self.root.after(CHECK_EVERY_MS, self.check_for_changes)

    def remember_size(self, event):
        """While the window isn't maximised, keep note of its size and place."""
        if event.widget is self.root and self.root.state() == "normal":
            self.normal_geometry = self.root.geometry()

    def close_window(self):
        """Remember how the window looks (maximised, or its size and place), then close."""
        maximised = self.root.state() == "zoomed"
        # The normal (not maximised) size and place, kept up to date by remember_size,
        # so un-maximising next time goes back to it.
        geometry = getattr(self, "normal_geometry", None) or self.root.geometry()
        try:
            settings.save_window({"maximised": maximised, "geometry": geometry})
        except OSError:
            pass
        self.root.destroy()

    # ------------------------------------------------------------------
    # Finding ideas
    # ------------------------------------------------------------------
    @property
    def ideas(self):
        return self.store.ideas

    def idea(self, name):
        return self.store.find(name)

    def chronological(self):
        """All ideas, oldest first."""
        return sorted(self.ideas, key=lambda i: i["created"])

    # ------------------------------------------------------------------
    # Left: the sidebar
    # ------------------------------------------------------------------
    def build_sidebar(self):
        bar = tk.Frame(self.root, bg=SIDEBAR_BG, width=SIDEBAR_WIDTH)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)   # keep the width we asked for
        tk.Frame(self.root, bg=EDGE, width=1).pack(side="left", fill="y")   # thin divider

        tk.Label(bar, text="Protostar", bg=SIDEBAR_BG, fg=TEXT, font=(FONT_BOLD, 15),
                 anchor="w", padx=18, pady=16).pack(fill="x")

        # "New idea": presses the capture shortcut for you, which opens the note
        # (if Protostar is running in the background).
        new = row(bar, self.new_idea, height=36)
        new.pack(fill="x", padx=10, pady=(0, 10))
        new.add("＋", font=(FONT, 12), colour=DIM_TEXT, gap=8).add("New idea", font=(FONT, 10), colour=TEXT)

        self.count_label = tk.Label(bar, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9), anchor="w",
                                    padx=18, pady=6)
        self.count_label.pack(fill="x")

        self.tree = ScrollArea(bar, SIDEBAR_BG)
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 10))

    def fill_sidebar(self):
        """(Re)build the folders and idea rows in the sidebar."""
        self.tree.clear()
        self.idea_rows = {}
        self.count_label.config(text=f"IDEAS  ·  {len(self.ideas)}")
        if not self.ideas:
            shortcut = settings.hotkey_spec(SETTINGS.get("capture_hotkey"), "ctrl_alt_i")[0]
            tk.Label(self.tree.inner, text=f"No ideas yet.\nPress {shortcut} to catch one.",
                     bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 10), justify="left",
                     anchor="w", padx=10, pady=8).pack(fill="x")
            self.add_trash_folder()
            return
        self.add_pinned_section()
        # Group ideas by month, newest month first, newest idea first.
        months = {}
        for idea in reversed(self.chronological()):
            months.setdefault(idea["created"][:7], []).append(idea)   # "2026-11"
        newest = max(months)
        for month in sorted(months, reverse=True):
            # Only the newest month starts open; the others open when clicked.
            # (With hundreds of ideas, building every row would be slow.)
            is_open = month in self.opened_months or (month == newest and month not in self.closed_months)
            name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            folder = row(self.tree.inner, lambda m=month: self.toggle_month(m), height=32)
            folder.pack(fill="x", pady=(4, 0))
            folder.add("▾" if is_open else "▸", font=(FONT, 9), colour=DIM_TEXT, gap=8)
            folder.add(name, font=(FONT_BOLD, 10), colour=SOFT_TEXT)
            folder.add(str(len(months[month])), side="right", font=(FONT, 9), colour=DIM_TEXT)
            if is_open:
                for idea in months[month]:
                    self.add_idea_row(idea)
        self.add_trash_folder()

    def add_trash_folder(self):
        """
        The Trash, at the bottom of the list: deleted ideas wait here for 30
        days. "Restore" brings one back (to the same place in the galaxy, with
        its notes and links); "Delete forever" removes it now.
        """
        trash = sorted(self.store.trash, key=lambda i: i["deleted"], reverse=True)
        if not trash:
            return
        is_open = "trash" not in self.closed_months and self.trash_open
        folder = row(self.tree.inner, self.toggle_trash, height=32)
        folder.pack(fill="x", pady=(14, 0))
        folder.add("▾" if is_open else "▸", font=(FONT, 9), colour=DIM_TEXT, gap=8)
        folder.add("Trash", font=(FONT_BOLD, 10), colour=DIM_TEXT)
        folder.add(str(len(trash)), side="right", font=(FONT, 9), colour=DIM_TEXT)
        if not is_open:
            return
        for idea in trash:
            box = tk.Frame(self.tree.inner, bg=SIDEBAR_BG)
            box.pack(fill="x", padx=(40, 10), pady=(4, 0))
            title = title_and_text(idea)[0] or "(no title)"
            tk.Label(box, text=title if len(title) <= 30 else title[:29] + "…", bg=SIDEBAR_BG,
                     fg=DIM_TEXT, font=(FONT, 10), anchor="w").pack(fill="x")
            days_left = TRASH_DAYS - (datetime.now() - datetime.fromisoformat(idea["deleted"])).days
            line = tk.Frame(box, bg=SIDEBAR_BG)
            line.pack(fill="x")
            small_button(line, "Restore", lambda n=idea["created"]: self.restore(n),
                         colour=SOFT_TEXT).pack(side="left")
            tk.Label(line, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
            small_button(line, "Delete forever", lambda n=idea["created"]: self.delete_forever(n),
                         colour=DANGER).pack(side="left")
            tk.Label(line, text=f"{days_left} d", bg=SIDEBAR_BG, fg=DIM_TEXT,
                     font=(FONT, 8)).pack(side="right")

    def toggle_trash(self):
        self.trash_open = not self.trash_open
        self.fill_sidebar()

    def restore(self, name):
        self.store.restore_idea(name)
        self.after_change()
        self.go_to(name)

    def delete_forever(self, name):
        idea = next((i for i in self.store.trash if i["created"] == name), None)
        title = title_and_text(idea)[0] if idea else ""
        if messagebox.askyesno("Delete forever", f"Delete “{title}” forever?\n\nThis can't be undone.",
                               icon="warning", parent=self.root):
            self.store.delete_forever(name)
            self.after_change()

    def pinned_names(self):
        return {i["created"] for i in self.ideas if i.get("pinned")}

    def toggle_pin(self, name):
        self.store.toggle_pin(name)
        self.after_change()

    def add_pinned_section(self):
        """Pinned ideas, always at the top of the list."""
        pinned = [i for i in reversed(self.chronological()) if i.get("pinned")]
        if not pinned:
            return
        tk.Label(self.tree.inner, text="PINNED", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 7),
                 anchor="w", padx=12).pack(fill="x", pady=(2, 2))
        for idea in pinned:
            name = idea["created"]
            title = title_and_text(idea)[0] or "(no title)"
            line = row(self.tree.inner, lambda n=name: self.go_to(n), selected=name == self.selected)
            line.pack(fill="x", pady=1)
            line.add("⬩", font=(FONT, 9), colour=ACCENT, gap=8)
            line.add(title if len(title) <= 28 else title[:27] + "…", font=(FONT, 10), colour=SOFT_TEXT)
        tk.Frame(self.tree.inner, bg=EDGE, height=1).pack(fill="x", padx=10, pady=(8, 4))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    # Settings that change how the app looks (preview = rebuild the window),
    # and settings that the background part uses (applied on Save by restarting it).
    LOOK = {"theme", "accent", "font", "detail"}
    BACKGROUND = {"capture_hotkey", "map_hotkey", "capture_save", "font", "theme", "accent"}

    def open_settings(self):
        """
        The Settings window. Every click shows its effect right away (a
        preview), but nothing is kept until you press Save. Closing the
        window or Cancel puts everything back as it was.
        """
        if getattr(self, "settings_window", None) and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.saved = dict(SETTINGS)              # what's saved on disk
        self.draft = dict(SETTINGS)              # what you're trying out
        self.draft["_autostart"] = self.saved["_autostart"] = startup.is_installed()
        win = tk.Toplevel(self.root)
        win.title("Protostar settings")
        win.geometry(f"560x720+{self.root.winfo_x() + 120}+{self.root.winfo_y() + 60}")
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self.cancel_settings)     # the window's × = Cancel
        win.bind("<Escape>", lambda e: self.cancel_settings() if not getattr(self, "recording", None) else None)
        dark_title_bar(win)
        self.settings_window = win
        self.settings_scroll = 0.0
        self.fill_settings()

    def fill_settings(self):
        """(Re)build the Settings window in the current colours, keeping the scroll position."""
        win = self.settings_window
        if getattr(self, "settings_area", None) is not None and self.settings_area.winfo_exists():
            self.settings_scroll = self.settings_area.canvas.yview()[0]
        for child in win.winfo_children():
            child.destroy()
        win.configure(bg=SIDEBAR_BG)
        # Save / Cancel at the bottom, always visible.
        footer = tk.Frame(win, bg=SIDEBAR_BG)
        footer.pack(side="bottom", fill="x", padx=16, pady=(6, 14))
        tk.Frame(win, bg=EDGE, height=1).pack(side="bottom", fill="x")
        changed = {k for k in self.draft if self.draft[k] != self.saved.get(k)}
        hint = "Changes are shown as a preview until you save." if changed else "Nothing changed."
        tk.Label(footer, text=hint, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8), anchor="w").pack(side="left")
        measure = tkfont.Font(font=(FONT, 10)).measure
        for label, command, primary in (("Save", self.save_settings, True),
                                        ("Cancel", self.cancel_settings, False)):
            button = widgets.Row(footer, SIDEBAR_BG, command, height=32, radius=16, hover=ROW_HOVER,
                                 selected_colour=_T["growing"] if primary else ROW_SELECTED,
                                 selected=True, padx=16)
            button.configure(width=measure(label) + 34)
            button.add(label, font=(FONT, 10), colour=ACCENT if primary else SOFT_TEXT)
            button.pack(side="right", padx=(8, 0))

        area = ScrollArea(win, SIDEBAR_BG)
        area.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        self.settings_area = area
        inner = area.inner
        tk.Label(inner, text="Settings", bg=SIDEBAR_BG, fg=TEXT, font=(FONT_BOLD, 15), anchor="w",
                 padx=8).pack(fill="x", pady=(4, 12))

        def section(title):
            tk.Label(inner, text=title.upper(), bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 7), anchor="w",
                     padx=8).pack(fill="x", pady=(14, 4))

        def option(label, hint, key, choices):
            """A setting: its name, a short explanation, and one pill per choice."""
            box = tk.Frame(inner, bg=SIDEBAR_BG)
            box.pack(fill="x", padx=8, pady=(4, 6))
            tk.Label(box, text=label, bg=SIDEBAR_BG, fg=TEXT, font=(FONT, 10), anchor="w").pack(fill="x")
            if hint:
                tk.Label(box, text=hint, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8), anchor="w",
                         justify="left", wraplength=480).pack(fill="x")
            line = tk.Frame(box, bg=SIDEBAR_BG)
            line.pack(fill="x", pady=(5, 0))
            measure = tkfont.Font(font=(FONT, 9)).measure
            for value, name in choices:
                chosen = self.draft.get(key) == value
                pill = widgets.Row(line, SIDEBAR_BG, lambda v=value: self.change_setting(key, v),
                                   height=26, radius=13, hover=ROW_HOVER,
                                   selected_colour=_T["growing"] if chosen else ROW_SELECTED,
                                   selected=True, padx=12)
                pill.configure(width=measure(name) + 26)
                pill.add(name, font=(FONT, 9), colour=ACCENT if chosen else SOFT_TEXT)
                pill.pack(side="left", padx=(0, 6))

        section("Look")
        option("Theme", "The colours of the panels (and of the capture note). The galaxy is always space-black.",
               "theme", [(k, v["name"]) for k, v in settings.THEMES.items()])
        option("Accent colour", "Used for highlights, the selection ring and the text box you type in.",
               "accent", [(k, v["name"]) for k, v in settings.ACCENTS.items()])
        option("Font", None, "font", [("inter", "Inter"), ("segoe", "Segoe UI (Windows)")])
        option("Star colours", "Natural star colours, or each star takes the colour of its first #tag.",
               "star_colours", [("natural", "Natural"), ("tags", "By #tag")])
        section("Galaxy")
        option("Detail", "How many points of light each idea brings. Use Low on older or slower PCs.",
               "detail", [(k, v["name"]) for k, v in settings.DETAIL.items()])
        option("Animations", "Smooth camera flights and the flash when a new star is born.",
               "animations", [(True, "On"), (False, "Off")])
        section("Capture note")
        self.shortcut_option(inner, "Shortcut: new idea", "capture_hotkey", "ctrl_alt_i")
        self.shortcut_option(inner, "Shortcut: open the galaxy", "map_hotkey", "ctrl_alt_m")
        option("Saving", "Which key saves the idea, and which one starts a new line.", "capture_save",
               [("enter", "Enter saves"), ("ctrl_enter", "Ctrl+Enter saves")])
        section("System")
        option("Start with Windows", None, "_autostart", [(True, "On"), (False, "Off")])
        area.update_idletasks()
        area.canvas.yview_moveto(self.settings_scroll)

    # --- Recording a shortcut ("press the keys you want") ---
    def shortcut_option(self, inner, label, key, default):
        """A shortcut setting: the current keys, plus Change… (record new keys) and Reset."""
        box = tk.Frame(inner, bg=SIDEBAR_BG)
        box.pack(fill="x", padx=8, pady=(4, 6))
        tk.Label(box, text=label, bg=SIDEBAR_BG, fg=TEXT, font=(FONT, 10), anchor="w").pack(fill="x")
        line = tk.Frame(box, bg=SIDEBAR_BG)
        line.pack(fill="x", pady=(5, 0))
        recording = getattr(self, "recording", None) == key
        name = settings.hotkey_spec(self.draft.get(key), default)[0]
        text = "Press the new shortcut…   (Esc to cancel)" if recording else name
        chip = widgets.Row(line, SIDEBAR_BG, None, height=26, radius=13, selected=True,
                           selected_colour=_T["growing"], padx=12)
        chip.configure(width=tkfont.Font(font=(FONT, 9)).measure(text) + 26)
        chip.add(text, font=(FONT, 9), colour=ACCENT)
        chip.pack(side="left", padx=(0, 10))
        if not recording:
            small_button(line, "Change…", lambda: self.start_recording(key)).pack(side="left", padx=(0, 10))
            if self.draft.get(key) != default:
                small_button(line, "Reset", lambda: self.change_setting(key, default)).pack(side="left")
        error = getattr(self, "record_error", None)
        if error and error[0] == key:
            tk.Label(box, text=error[1], bg=SIDEBAR_BG, fg=DANGER, font=(FONT, 8), anchor="w",
                     justify="left", wraplength=480).pack(fill="x", pady=(4, 0))

    def start_recording(self, key):
        self.recording = key
        self.record_error = None
        self.settings_window.bind("<KeyPress>", self.record_key)
        self.settings_window.focus_force()
        self.fill_settings()

    def stop_recording(self, error=None):
        if error:
            self.record_error = (self.recording, error)
        self.recording = None
        self.settings_window.unbind("<KeyPress>")
        self.fill_settings()

    def record_key(self, event):
        """
        A key was pressed while recording. Holding Ctrl/Alt/Shift alone does
        nothing yet; the first "real" key completes the shortcut.

        Tkinter tells us which extra keys were held in event.state, a number
        where each "bit" means one key: 0x1 = Shift, 0x4 = Ctrl, 0x20000 = Alt.
        event.keycode is Windows' own number for the key: exactly what
        RegisterHotKey needs.
        """
        key = self.recording
        if event.keysym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R",
                            "Win_L", "Win_R", "Caps_Lock", "Num_Lock"):
            return "break"
        ctrl, alt, shift = bool(event.state & 0x4), bool(event.state & 0x20000), bool(event.state & 0x1)
        if event.keysym == "Escape" and not (ctrl or alt or shift):
            self.stop_recording()
            return "break"
        is_f_key = event.keysym.startswith("F") and event.keysym[1:].isdigit()
        if not (ctrl or alt or is_f_key):
            self.stop_recording("Use Ctrl or Alt together with a key (like Ctrl+Alt+N), so the "
                                "shortcut doesn't get in the way of normal typing.")
            return "break"
        mods = (1 if alt else 0) | (2 if ctrl else 0) | (4 if shift else 0)
        vk = event.keycode
        key_name = {"space": "Space", "Return": "Enter", "Tab": "Tab"}.get(event.keysym)
        if key_name is None:
            key_name = event.keysym.upper() if len(event.keysym) == 1 else event.keysym
        name = "+".join([p for p, on in (("Ctrl", ctrl), ("Alt", alt), ("Shift", shift)) if on] + [key_name])
        other = "map_hotkey" if key == "capture_hotkey" else "capture_hotkey"
        other_spec = settings.hotkey_spec(self.draft.get(other), "ctrl_alt_m" if other == "map_hotkey" else "ctrl_alt_i")
        if (mods, vk) == (3, 0x51):
            return self.stop_recording("Ctrl+Alt+Q is kept for quitting Protostar.") or "break"
        if (mods, vk) == other_spec[1:]:
            return self.stop_recording(f"{name} is already the other shortcut.") or "break"
        # Is another program using it? Try to borrow it for a moment. (Our own
        # background part holds the current shortcuts, so those count as free.)
        own = {settings.hotkey_spec(self.saved.get(k), d)[1:] for k, d in
               (("capture_hotkey", "ctrl_alt_i"), ("map_hotkey", "ctrl_alt_m"))}
        user32 = ctypes.WinDLL("user32")
        if (mods, vk) not in own:
            if not user32.RegisterHotKey(None, 0xB0B0, mods | 0x4000, vk):
                return self.stop_recording(f"{name} is already used by another program. "
                                           "Try a different combination.") or "break"
            user32.UnregisterHotKey(None, 0xB0B0)
        self.recording = None
        self.settings_window.unbind("<KeyPress>")
        self.change_setting(key, {"name": name, "mods": mods, "vk": vk})
        return "break"

    def change_setting(self, key, value):
        """A click in Settings: try it out right away (nothing is saved yet)."""
        self.draft[key] = value
        self.preview(self.draft)
        self.fill_settings()

    def preview(self, values):
        """Make the app look and behave like `values`, without saving anything."""
        look_changed = any(values[k] != SETTINGS.get(k) for k in self.LOOK)
        SETTINGS.update({k: v for k, v in values.items() if not k.startswith("_")})
        if look_changed:
            apply_look(SETTINGS)
            self.rebuild_ui()
        else:
            self.update_highlights()           # star colours / animations
            self.request_sharp()

    def save_settings(self):
        """Keep the changes: save them, and restart the background part if it uses them."""
        changed = {k for k in self.draft if self.draft[k] != self.saved.get(k)}
        if "_autostart" in changed:
            if self.draft["_autostart"]:
                startup.make_shortcut()
            elif startup.SHORTCUT.exists():
                startup.SHORTCUT.unlink()
        settings.save({k: v for k, v in self.draft.items() if not k.startswith("_")})
        if changed & self.BACKGROUND:
            # The capture note and the shortcuts live in the background part:
            # restart it so it picks up the new settings.
            startup.stop_running()
            startup.start_now()
        self.settings_window.destroy()
        self.flash("Settings saved" if changed else "Settings closed")

    def cancel_settings(self):
        """Close Settings without keeping anything: undo the preview."""
        if getattr(self, "recording", None):
            self.recording = None
        self.settings_window.destroy()
        self.preview({k: v for k, v in self.saved.items()})

    def rebuild_ui(self):
        """
        Rebuild the whole window in the new colours and font, in place: the
        selected idea, open ideas and folders, the search text and the camera
        position are all kept, so it looks like the colours simply changed.
        """
        query = self.query.get() if hasattr(self, "query") else ""
        self.anim = None
        for child in self.root.winfo_children():
            if child is not getattr(self, "settings_window", None):
                child.destroy()
        self.root.configure(bg=SIDEBAR_BG)
        self.stats_panel = None
        self.calendar_panel = None
        self.build_sidebar()
        self.build_search_panel()
        self.build_middle()
        self.build_scene()
        self.fill_sidebar()
        self.update_topbar()
        if query:
            self.query.set(query)
        if np.linalg.norm(self.goal.position - self.camera.position) > 1e-6:
            self.start_animation()             # finish a camera flight that was under way
        self.request_sharp()

    def toggle_stats(self):
        """A small panel over the galaxy with numbers about your ideas."""
        if self.stats_panel is not None:
            self.stats_panel.destroy()
            self.stats_panel = None
            return
        s = self.store.stats()
        streak = f"{s['streak']} day{'s' if s['streak'] != 1 else ''}"
        rows = [("Ideas", s["ideas"]), ("This week", s["this week"]), ("This month", s["this month"]),
                ("Streak", streak), ("Growing", s["growing"]), ("Done", s["done"]),
                ("Notes", s["notes"]), ("Links", s["links"])]
        w = 230
        h = 40 + 24 * len(rows) + (44 if s["hub"] else 0)
        panel = tk.Canvas(self.view.master, bg=g3d.SPACE_HEX, highlightthickness=0, width=w, height=h)
        panel.create_image(0, 0, anchor="nw",
                           image=widgets.rounded_image(w, h, 12, CARD_BG, g3d.SPACE_HEX, CARD_EDGE))
        panel.create_text(18, 22, text="Stats", anchor="w", fill=CARD_TEXT, font=(FONT_BOLD, 11))
        y = 50
        for label, value in rows:
            panel.create_text(18, y, text=label, anchor="w", fill=DIM_TEXT, font=(FONT, 9))
            panel.create_text(w - 18, y, text=str(value), anchor="e", fill=CARD_TEXT, font=(FONT, 10))
            y += 24
        if s["hub"]:
            title, count = s["hub"]
            panel.create_text(18, y + 2, text="Most connected", anchor="w", fill=DIM_TEXT, font=(FONT, 9))
            panel.create_text(18, y + 20, text=f"{title[:26]}  ({count} links)", anchor="w",
                              fill="#aeb6c4", font=(FONT, 9))
        panel.bind("<Button-1>", lambda e: self.toggle_stats())    # click it to close
        panel.place(in_=self.view, relx=1.0, x=-14, y=14, anchor="ne")
        # On a Canvas, .lift() means "raise a drawing"; tk.Misc.lift raises the widget itself.
        tk.Misc.lift(panel)
        self.stats_panel = panel

    def set_stage(self, name, stage):
        self.store.set_stage(name, stage)
        self.after_change()

    def add_idea_row(self, idea):
        name = idea["created"]
        title, text = title_and_text(idea)
        selected = name == self.selected
        box = tk.Frame(self.tree.inner, bg=SIDEBAR_BG)
        box.pack(fill="x")
        line = row(box, lambda: self.click_idea(name), selected=selected)
        line.pack(fill="x", padx=(18, 0), pady=1)
        is_open = name in self.open_ideas
        line.add("▾" if is_open else "▸", font=(FONT, 8), colour=DIM_TEXT, gap=8)
        rgb = g3d.STAR_COLOURS[colour_index(idea)]
        if LIGHT_THEME:      # white dots would vanish on light panels: draw them darker
            rgb = tuple(c * 0.55 for c in rgb)
        star = GOLD if idea.get("stage") == "done" else hex_colour(rgb)
        line.add("●", font=(FONT, 6), colour=star, gap=7)
        if name in self.pinned_names():
            line.add("⬩", font=(FONT, 9), colour=ACCENT, gap=4)      # pinned
        shown = title if len(title) <= 26 else title[:25] + "…"
        line.add(shown or "(no title)", font=(FONT, 10), colour=TEXT if selected else SOFT_TEXT)
        notes = self.store.notes_of(idea)
        if notes:   # how many notes this idea has, in small grey numbers on the right
            line.add(str(len(notes)), side="right", font=(FONT, 8), colour=DIM_TEXT)
        if idea.get("due") and idea.get("stage") != "done":     # ⏰ has a deadline (red: overdue)
            late = idea["due"] < datetime.now().isoformat(timespec="minutes")
            line.add("⏰", side="right", font=(FONT, 8), colour=DANGER if late else DIM_TEXT)
        mark = STAGE_MARK.get(idea.get("stage"))
        if mark:    # ✦ growing, ★ done
            line.add(mark, side="right", font=(FONT, 8), colour=GOLD if mark == "★" else ACCENT)
        if is_open:
            body = tk.Frame(box, bg=SIDEBAR_BG)
            body.pack(fill="x", padx=(44, 10), pady=(0, 10))
            if self.editing == name:
                self.fill_edit_form(body, idea)
            else:
                self.fill_open_idea(body, idea)
        self.idea_rows[name] = box

    def fill_open_idea(self, body, idea):
        """An opened idea: date, text, notes, linked ideas, buttons, and a note box."""
        name = idea["created"]
        title, text = title_and_text(idea)
        when = datetime.fromisoformat(name).strftime("%d %b %Y, %H:%M")
        tk.Label(body, text=when, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8), anchor="w").pack(fill="x")
        if text:
            tk.Label(body, text=text, bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT, 10),
                     wraplength=SIDEBAR_WIDTH - 70, justify="left", anchor="w").pack(fill="x", pady=(2, 0))

        # Notes, each with small "edit" and "delete" buttons.
        for note in self.store.notes_of(idea):
            line = tk.Frame(body, bg=SIDEBAR_BG)
            line.pack(fill="x", pady=(6, 0))
            if self.editing_note == note["created"]:
                box = text_input(line, note["text"], font_size=9)
                box.pack(fill="x")
                box.field.focus_set()
                box.field.bind("<Return>", lambda e, n=note, b=box: self.finish_note_edit(name, n, b.field.get()))
                box.field.bind("<Escape>", lambda e: self.cancel_edits())
                continue
            tk.Label(line, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 10)).pack(side="left", anchor="n")
            small_button(line, "×", lambda n=note: self.delete_note(name, n)).pack(side="right", anchor="n")
            small_button(line, "✎", lambda n=note: self.start_note_edit(n)).pack(side="right", anchor="n", padx=(4, 2))
            tk.Label(line, text=note["text"], bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT, 9),
                     wraplength=SIDEBAR_WIDTH - 110, justify="left", anchor="w").pack(side="left", fill="x", padx=(4, 0))

        # Linked ideas (constellation partners); click one to go there.
        linked = self.store.linked_to(idea)
        if linked:
            tk.Label(body, text="LINKED", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 7),
                     anchor="w").pack(fill="x", pady=(10, 0))
        for other in linked:
            line = tk.Frame(body, bg=SIDEBAR_BG)
            line.pack(fill="x", pady=(2, 0))
            other_title = title_and_text(other)[0] or "(no title)"
            small_button(line, "×", lambda o=other: self.unlink(name, o["created"])).pack(side="right")
            small_button(line, "✦ " + (other_title if len(other_title) < 30 else other_title[:29] + "…"),
                         lambda o=other: self.go_to(o["created"]), colour=SOFT_TEXT).pack(side="left")

        # Life stage: Spark · Growing · Done (click to change).
        stages = tk.Frame(body, bg=SIDEBAR_BG)
        stages.pack(fill="x", pady=(10, 0))
        current = idea.get("stage", "spark")
        for stage, label in STAGE_NAMES.items():
            if stage == current:
                self.pill(stages, label, stage).pack(side="left", padx=(0, 6))
            else:
                small_button(stages, label, lambda s=stage: self.set_stage(name, s)).pack(side="left", padx=(0, 6))

        self.add_deadline_section(body, idea)

        # Buttons: Edit · Link · Delete
        actions = tk.Frame(body, bg=SIDEBAR_BG)
        actions.pack(fill="x", pady=(8, 0))
        small_button(actions, "Edit", lambda: self.start_edit(name)).pack(side="left")
        tk.Label(actions, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(actions, "Unpin" if idea.get("pinned") else "Pin",
                     lambda: self.toggle_pin(name)).pack(side="left")
        tk.Label(actions, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(actions, "Link to…", lambda: self.start_link(name)).pack(side="left")
        tk.Label(actions, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(actions, "Delete", lambda: self.delete_idea(name), colour=DANGER).pack(side="left")

        self.add_note_box(body, idea)

    def pill(self, parent, text, stage="spark"):
        """A small rounded label: the chosen life stage, in its own colour."""
        fill, colour = STAGE_PILL.get(stage, STAGE_PILL["spark"])
        width = tkfont.Font(font=(FONT, 8)).measure(text) + 18
        chip = widgets.Row(parent, SIDEBAR_BG, None, height=20, radius=10, selected=True,
                           selected_colour=fill, padx=9)
        chip.configure(width=width)
        chip.add(text, font=(FONT, 8), colour=colour)
        return chip

    def fill_edit_form(self, body, idea):
        """The idea turned into text fields: change the title and text, then Save."""
        title, text = title_and_text(idea)
        title_box = text_input(body, title, font_size=10)
        title_box.pack(fill="x")
        text_box = text_input(body, text, height=5, font_size=9)
        text_box.pack(fill="x", pady=(6, 0))
        autoformat.attach(text_box.field, "<Return>")      # Enter = new line here; Save is a button
        buttons = tk.Frame(body, bg=SIDEBAR_BG)
        buttons.pack(fill="x", pady=(6, 0))

        def save():
            self.store.edit_idea(idea["created"], title_box.field.get().strip(),
                                 text_box.field.get("1.0", "end").strip())
            self.after_change()

        small_button(buttons, "Save", save, colour=ACCENT).pack(side="left")
        tk.Label(buttons, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(buttons, "Cancel", self.cancel_edits).pack(side="left")
        title_box.field.focus_set()
        title_box.field.bind("<Return>", lambda e: save())
        title_box.field.bind("<Escape>", lambda e: self.cancel_edits())

    def add_note_box(self, parent, idea):
        """
        A text box under an open idea for a new note. It grows as you write
        (up to 8 lines), formats bullets and capitals as you type, and has two
        buttons: ⤢ writes the note in the big capture box instead, 🎙 starts
        Windows voice typing. Saving uses the same key as the capture note.
        """
        hint = "Add a note…"
        save_with_ctrl = SETTINGS["capture_save"] == "ctrl_enter"
        holder = tk.Frame(parent, bg=SIDEBAR_BG)
        holder.pack(fill="x", pady=(10, 0))
        buttons = tk.Frame(holder, bg=SIDEBAR_BG)
        buttons.pack(side="right", anchor="n", padx=(6, 0), pady=(6, 0))
        box = text_input(holder, hint, height=1, font_size=9)
        box.pack(side="left", fill="x", expand=True)
        entry = box.field
        entry.config(fg=DIM_TEXT)
        small_button(buttons, "⤢", lambda: self.note_in_big_box(idea)).pack(anchor="n")
        small_button(buttons, "🎙", lambda: dictate(entry)).pack(anchor="n", pady=(4, 0))

        def written():
            return entry.get("1.0", "end").strip()

        def grow(event=None):
            # As many lines as the note needs ("display lines" count wrapped lines too).
            lines = entry.count("1.0", "end", "displaylines") or (1,)
            entry.config(height=max(1, min(8, lines[0])))

        def focus_in(event):
            if written() == hint:                # remove the grey hint when you click in
                entry.delete("1.0", "end")
                entry.config(fg=TEXT)

        def focus_out(event):
            if not written():                    # put the hint back if you left it empty
                entry.insert("1.0", hint)
                entry.config(fg=DIM_TEXT)

        def save(event):
            text = written()
            if text and text != hint:
                self.store.add_note(idea["created"], text)
                self.after_change()
            return "break"                       # don't also add a new line

        entry.bind("<FocusIn>", focus_in, add="+")
        entry.bind("<FocusOut>", focus_out, add="+")
        entry.bind("<Control-Return>" if save_with_ctrl else "<Return>", save)
        entry.bind("<KeyRelease>", grow, add="+")
        entry.bind("<Escape>", lambda e: self.canvas.focus_set())
        autoformat.attach(entry, "<Return>" if save_with_ctrl else "<Shift-Return>")

    # --- Deadlines ---
    def add_deadline_section(self, body, idea):
        """The deadline of an open idea: shown, or edited (date, time and reminders)."""
        name = idea["created"]
        box = tk.Frame(body, bg=SIDEBAR_BG)
        box.pack(fill="x", pady=(8, 0))
        if self.editing_due == name:
            self.fill_deadline_editor(box, idea)
            return
        if idea.get("due"):
            late = idea["due"] < datetime.now().isoformat(timespec="minutes") and idea.get("stage") != "done"
            tk.Label(box, text="⏰ " + reminders.describe_due(idea["due"]), bg=SIDEBAR_BG,
                     fg=DANGER if late else SOFT_TEXT, font=(FONT, 9), anchor="w").pack(fill="x")
            labels = [reminders.LABELS.get(m, f"{m} min before") for m in idea.get("remind", [])]
            if labels:
                tk.Label(box, text="Reminders: " + ", ".join(labels), bg=SIDEBAR_BG, fg=DIM_TEXT,
                         font=(FONT, 8), anchor="w", justify="left",
                         wraplength=SIDEBAR_WIDTH - 70).pack(fill="x")
            line = tk.Frame(box, bg=SIDEBAR_BG)
            line.pack(fill="x", pady=(2, 0))
            small_button(line, "Change deadline", lambda: self.edit_deadline(name)).pack(side="left")
            tk.Label(line, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
            small_button(line, "Remove", lambda: self.save_deadline(name, None, [])).pack(side="left")
        else:
            small_button(box, "⏰  Set a deadline…", lambda: self.edit_deadline(name)).pack(anchor="w")

    def edit_deadline(self, name):
        """Open the deadline editor for an idea (starting from its deadline, or tomorrow at 18:00)."""
        idea = self.idea(name)
        current = datetime.fromisoformat(idea["due"]) if idea.get("due") else None
        start = current or datetime.combine(datetime.now().date() + timedelta(days=1), datetime.min.time())
        self.editing_due = name
        self.due_date = start.date()
        self.due_time = (current.hour, current.minute) if current else (18, 0)
        # The 7-day strip starts on the Monday of the chosen day's week.
        self.due_week = self.due_date - timedelta(days=self.due_date.weekday())
        self.due_choice = set(idea.get("remind", [1440] if not current else []))
        self.remind_open = False
        self.fill_sidebar()

    def fill_deadline_editor(self, box, idea):
        """
        The deadline editor: nothing to type. A strip of 7 days (‹ › move a
        week), the time with − / + buttons (or the mouse wheel), and
        "Remind me", which opens a small scrolling list of reminder choices.

        Clicks only redraw the part that changed (the days, the numbers, the
        list), never the whole sidebar — so nothing flashes.
        """
        name = idea["created"]
        w = self.due_widgets = {}
        tk.Label(box, text="DEADLINE", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 7), anchor="w").pack(fill="x")

        # --- The days ---
        width = SIDEBAR_WIDTH - 76     # fits inside the open idea, with a small margin
        w["strip"] = tk.Canvas(box, bg=SIDEBAR_BG, height=74, width=width, highlightthickness=0)
        w["strip"].pack(anchor="w", pady=(4, 0))
        self.draw_due_strip()

        # --- The time: − hour + : − minutes + (steps of 15 minutes) ---
        clock = tk.Frame(box, bg=SIDEBAR_BG)
        clock.pack(anchor="w", pady=(6, 0))
        tk.Label(clock, text="Time", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8)).pack(side="left", padx=(0, 10))

        def stepper(key, change):
            small_button(clock, "−", lambda: change(-1)).pack(side="left")
            shown = tk.Label(clock, bg=SIDEBAR_BG, fg=TEXT, font=(FONT_BOLD, 11), width=3)
            shown.pack(side="left")
            # "break" = the wheel changes the time and doesn't also scroll the sidebar.
            shown.bind("<MouseWheel>", lambda e: (change(1 if e.delta > 0 else -1), "break")[1])
            small_button(clock, "+", lambda: change(1)).pack(side="left")
            w[key] = shown

        stepper("hour", self.step_due_hour)
        tk.Label(clock, text=":", bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT_BOLD, 11)).pack(side="left", padx=4)
        stepper("minute", self.step_due_minute)

        # --- Remind me ▸ / ▾ and the scrolling list ---
        w["summary"] = small_button(box, "", self.toggle_remind_open, colour=SOFT_TEXT)
        w["summary"].configure(wraplength=SIDEBAR_WIDTH - 70, justify="left")
        w["summary"].pack(anchor="w", pady=(8, 2))
        w["list_holder"] = tk.Frame(box, bg=SIDEBAR_BG)
        w["list_holder"].pack(fill="x")

        # --- Save / Cancel ---
        buttons = tk.Frame(box, bg=SIDEBAR_BG)
        buttons.pack(fill="x", pady=(8, 0))

        def save():
            due = datetime.combine(self.due_date, datetime.min.time()).replace(
                hour=self.due_time[0], minute=self.due_time[1])
            self.save_deadline(name, due.isoformat(timespec="minutes"), sorted(self.due_choice))

        small_button(buttons, "Save", save, colour=ACCENT).pack(side="left")
        tk.Label(buttons, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(buttons, "Cancel", self.cancel_deadline).pack(side="left")
        w["result"] = tk.Label(buttons, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8))
        w["result"].pack(side="right")
        self.update_due_labels()
        self.update_reminder_list()
        self.root.after(60, lambda: box.winfo_exists() and self.tree.scroll_to(box))   # make sure it's in view

    def draw_due_strip(self):
        """The month name, ‹ ›, and the 7 days of the strip (only this canvas is redrawn)."""
        strip = self.due_widgets["strip"]
        strip.delete("all")
        width = int(strip.cget("width"))
        cell = width / 7
        week = [self.due_week + timedelta(days=i) for i in range(7)]
        months = sorted({(d.year, d.month) for d in week})
        label = " / ".join(datetime(y, mo, 1).strftime("%B %Y" if i == len(months) - 1 else "%B")
                           for i, (y, mo) in enumerate(months))
        strip.create_text(2, 10, text=label, anchor="w", fill=SOFT_TEXT, font=(FONT, 9))
        for text, step, x in (("‹", -7, width - 34), ("›", 7, width - 10)):
            strip.create_text(x, 10, text=text, fill=SOFT_TEXT, font=(FONT, 13), tags=f"step{step}")
            strip.tag_bind(f"step{step}", "<Button-1>", lambda e, s=step: self.move_due_week(s))
        today = datetime.now().date()
        for i, day in enumerate(week):
            x = cell * i + cell / 2
            tag = f"d{i}"
            chosen = day == self.due_date
            if chosen:
                strip.create_image(x - cell / 2 + 2, 26, anchor="nw", tags=tag,
                                   image=widgets.rounded_image(int(cell) - 4, 44, 10, _T["growing"], SIDEBAR_BG))
            colour = ACCENT if chosen else (DIM_TEXT if day < today else (ACCENT if day == today else TEXT))
            strip.create_text(x, 38, text=day.strftime("%a")[:2], fill=ACCENT if chosen else DIM_TEXT,
                              font=(FONT, 7), tags=tag)
            strip.create_text(x, 56, text=str(day.day), fill=colour, font=(FONT_BOLD if chosen else FONT, 10),
                              tags=tag)
            strip.create_rectangle(x - cell / 2, 26, x + cell / 2, 72, outline="", fill="", tags=tag)
            strip.tag_bind(tag, "<Button-1>", lambda e, d=day: self.pick_due_date(d))

    def update_due_labels(self):
        """The time numbers, the "Remind me" summary and the result line."""
        w = self.due_widgets
        hour, minute = self.due_time
        w["hour"].config(text=f"{hour:02d}")
        w["minute"].config(text=f"{minute:02d}")
        chosen = [label for minutes, label in reminders.CHOICES if minutes in self.due_choice]
        summary = ("Remind me: " + ", ".join(chosen)) if chosen else "Remind me"
        w["summary"].config(text=summary + ("  ▾" if self.remind_open else "  ▸"))
        w["result"].config(text=self.due_date.strftime("%a %d %b") + f", {hour:02d}:{minute:02d}")

    REMINDER_ROW = 26        # height of one choice in the reminder list
    REMINDER_ROWS = 3        # how many choices show at once (scroll for the rest)

    def update_reminder_list(self):
        """
        Show or hide the reminder list: a small rounded box showing 3 choices
        at a time. Scroll it with the mouse wheel; click a choice to tick or
        untick it (✓). A slim bar on the right shows where you are in the list.
        """
        holder = self.due_widgets["list_holder"]
        if not self.remind_open:
            for child in holder.winfo_children():
                child.destroy()
            self.due_widgets.pop("list", None)
            return
        if "list" not in self.due_widgets:
            width = SIDEBAR_WIDTH - 76     # fits inside the open idea, with a small margin
            height = self.REMINDER_ROW * self.REMINDER_ROWS + 8
            frame = tk.Canvas(holder, bg=SIDEBAR_BG, width=width, height=height, highlightthickness=0)
            frame.pack(anchor="w")
            frame.create_image(0, 0, anchor="nw",
                               image=widgets.rounded_image(width, height, 10, INPUT_BG, SIDEBAR_BG, INPUT_EDGE))
            inner = tk.Canvas(frame, bg=INPUT_BG, width=width - 14, height=height - 8, highlightthickness=0)
            frame.create_window(4, 4, window=inner, anchor="nw")
            inner.configure(scrollregion=(0, 0, width - 14, self.REMINDER_ROW * len(reminders.CHOICES)))

            def wheel(event):
                inner.yview_scroll(-1 if event.delta > 0 else 1, "units")
                self.draw_reminder_list()
                return "break"                      # only this list scrolls, not the sidebar

            def click(event):
                n = int(inner.canvasy(event.y) // self.REMINDER_ROW)
                if 0 <= n < len(reminders.CHOICES):
                    self.toggle_due_choice(reminders.CHOICES[n][0])

            inner.configure(yscrollincrement=self.REMINDER_ROW)
            inner.bind("<MouseWheel>", wheel)
            inner.bind("<Button-1>", click)
            self.due_widgets["list"] = inner
            # Start with the first ticked choice in view.
            first = next((i for i, (m, _) in enumerate(reminders.CHOICES) if m in self.due_choice), 0)
            inner.yview_moveto(max(0, first - 1) / len(reminders.CHOICES))
        self.draw_reminder_list()

    def draw_reminder_list(self):
        inner = self.due_widgets.get("list")
        if inner is None:
            return
        inner.delete("all")
        width = int(inner.cget("width"))
        for n, (minutes, label) in enumerate(reminders.CHOICES):
            y = n * self.REMINDER_ROW
            on = minutes in self.due_choice
            if on:
                inner.create_image(0, y + 2, anchor="nw",
                                   image=widgets.rounded_image(width - 8, self.REMINDER_ROW - 4, 8,
                                                               _T["growing"], INPUT_BG))
            inner.create_text(12, y + self.REMINDER_ROW / 2, text="✓" if on else "○", anchor="w",
                              fill=ACCENT if on else DIM_TEXT, font=(FONT, 9))
            inner.create_text(32, y + self.REMINDER_ROW / 2, text=label, anchor="w",
                              fill=ACCENT if on else SOFT_TEXT, font=(FONT, 9))
        # The slim scroll bar: where the visible part sits in the whole list.
        top, bottom = inner.yview()
        total = self.REMINDER_ROW * len(reminders.CHOICES)
        view_h = int(inner.cget("height"))
        y0 = inner.canvasy(0)
        inner.create_rectangle(width - 4, y0 + top * view_h + 2, width - 1, y0 + bottom * view_h - 2,
                               fill=DIM_TEXT, outline="")

    def move_due_week(self, days):
        self.due_week += timedelta(days=days)
        self.draw_due_strip()

    def pick_due_date(self, day):
        self.due_date = day
        self.draw_due_strip()
        self.update_due_labels()

    def step_due_hour(self, step):
        hour, minute = self.due_time
        self.due_time = ((hour + step) % 24, minute)
        self.update_due_labels()

    def step_due_minute(self, step):
        """Minutes go in steps of 15; going past :45 or below :00 moves the hour too."""
        hour, minute = self.due_time
        total = (hour * 60 + minute + step * 15) % (24 * 60)
        self.due_time = (total // 60, total % 60)
        self.update_due_labels()

    def toggle_remind_open(self):
        self.remind_open = not self.remind_open
        self.update_due_labels()
        self.update_reminder_list()
        if self.remind_open:
            holder = self.due_widgets["list_holder"]
            self.root.after(30, lambda: holder.winfo_exists() and self.tree.scroll_to(holder))

    def toggle_due_choice(self, minutes):
        self.due_choice ^= {minutes}
        self.update_due_labels()
        self.draw_reminder_list()

    def cancel_deadline(self):
        self.editing_due = None
        self.fill_sidebar()

    def save_deadline(self, name, due, remind):
        self.editing_due = None
        self.store.set_due(name, due, remind)
        self.after_change()
        if self.calendar_panel is not None:
            self.draw_calendar()

    # --- Calendar ---
    def toggle_calendar(self):
        """A month calendar over the galaxy: what was added on each day, and what's due when."""
        if self.calendar_panel is not None:
            self.calendar_panel.destroy()
            self.calendar_panel = None
            return
        today = datetime.now().date()
        self.calendar_month = (today.year, today.month)
        self.calendar_day = today
        self.calendar_panel = tk.Canvas(self.view.master, bg=g3d.SPACE_HEX, highlightthickness=0)
        self.calendar_panel.place(in_=self.view, relx=1.0, x=-14, y=14, anchor="ne")
        tk.Misc.lift(self.calendar_panel)
        self.draw_calendar()

    def draw_calendar(self):
        import calendar as cal
        c = self.calendar_panel
        c.delete("all")
        year, month = self.calendar_month
        added, due = {}, {}
        for idea in self.ideas:
            added.setdefault(idea["created"][:10], []).append(idea)
            if idea.get("due"):
                due.setdefault(idea["due"][:10], []).append(idea)
        cell, left, top = 38, 18, 78
        weeks = cal.Calendar(firstweekday=0).monthdatescalendar(year, month)
        day = self.calendar_day
        chosen_added = added.get(day.isoformat(), [])
        chosen_due = due.get(day.isoformat(), [])
        entries = [("Due", i) for i in chosen_due] + [("Added", i) for i in chosen_added]
        w = left * 2 + cell * 7
        h = top + cell * len(weeks) + 30 + 22 * max(1, len(entries)) + 14
        c.configure(width=w, height=h)
        c.create_image(0, 0, anchor="nw", image=widgets.rounded_image(w, h, 14, CARD_BG, g3d.SPACE_HEX, CARD_EDGE))
        c.create_text(left, 26, text=f"{cal.month_name[month]} {year}", anchor="w", fill=CARD_TEXT,
                      font=(FONT_BOLD, 11))
        for label, step, x in (("‹", -1, w - 62), ("›", 1, w - 30)):
            arrow = c.create_text(x, 26, text=label, fill="#aeb6c4", font=(FONT, 14), tags=f"nav{step}")
            c.tag_bind(f"nav{step}", "<Button-1>", lambda e, s=step: self.move_calendar(s))
        for i, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            c.create_text(left + cell * i + cell / 2, top - 18, text=name, fill="#6f7889", font=(FONT, 8))
        today = datetime.now().date()
        for r, week in enumerate(weeks):
            for i, d in enumerate(week):
                x, y = left + cell * i + cell / 2, top + cell * r + cell / 2
                tag = f"day{d.isoformat()}"
                if d == day:
                    c.create_oval(x - 15, y - 15, x + 15, y + 15, fill="#242b37", outline="", tags=tag)
                if d.isoformat() in due:
                    late = d < today and any(i2.get("stage") != "done" for i2 in due[d.isoformat()])
                    c.create_oval(x - 14, y - 14, x + 14, y + 14, outline=DANGER if late else ACCENT, width=1.5, tags=tag)
                colour = "#e7eaf0" if d.month == month else "#4a5262"
                if d == today:
                    colour = ACCENT
                c.create_text(x, y - 3, text=str(d.day), fill=colour, font=(FONT, 9), tags=tag)
                n = len(added.get(d.isoformat(), []))
                for k in range(min(n, 4)):         # one small dot per idea added that day (max 4)
                    dx = (k - (min(n, 4) - 1) / 2) * 5
                    c.create_oval(x + dx - 1.5, y + 8, x + dx + 1.5, y + 11, fill="#aeb6c4", outline="", tags=tag)
                c.create_rectangle(x - cell / 2, y - cell / 2, x + cell / 2, y + cell / 2, outline="", fill="",
                                   tags=tag)
                c.tag_bind(tag, "<Button-1>", lambda e, dd=d: self.pick_calendar_day(dd))
        y = top + cell * len(weeks) + 16
        c.create_text(left, y, text=f"{day:%A %d %B}", anchor="w", fill="#aeb6c4", font=(FONT, 9))
        y += 22
        if not entries:
            c.create_text(left, y, text="Nothing added or due on this day.", anchor="w", fill="#6f7889", font=(FONT, 9))
        for kind, idea in entries:
            title = title_and_text(idea)[0] or "(no title)"
            text = f"{'⏰' if kind == 'Due' else '✦'}  {title[:30]}" + (f"   {idea['due'][11:16]}" if kind == "Due" else "")
            tag = f"entry{id(idea)}{kind}"
            c.create_text(left, y, text=text, anchor="w", fill="#e7eaf0" if kind == "Due" else "#aeb6c4",
                          font=(FONT, 9), tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, n=idea["created"]: self.go_to(n))
            y += 22

    def move_calendar(self, step):
        year, month = self.calendar_month
        month += step
        if month == 0:
            year, month = year - 1, 12
        elif month == 13:
            year, month = year + 1, 1
        self.calendar_month = (year, month)
        self.draw_calendar()

    def pick_calendar_day(self, day):
        self.calendar_day = day
        if (day.year, day.month) != self.calendar_month:
            self.calendar_month = (day.year, day.month)
        self.draw_calendar()

    def note_in_big_box(self, idea):
        """
        Write a note in the big capture box (the Ctrl+Alt+I one), already set
        to this idea. We leave a small "request" file for the background part,
        then press the capture shortcut for you; the box reads the request.
        """
        request = self.store.path.parent / "capture_request.json"
        request.write_text(json.dumps({"parent": idea["created"],
                                       "title": title_and_text(idea)[0],
                                       "file": str(self.store.path)}), encoding="utf-8")
        self.new_idea()

    # --- Sidebar actions ---
    def toggle_month(self, month):
        if month in self.opened_months:
            self.opened_months.discard(month)
            self.closed_months.add(month)
        elif month in self.closed_months:
            self.closed_months.discard(month)
            self.opened_months.add(month)
        elif month == max(i["created"][:7] for i in self.ideas):
            self.closed_months.add(month)              # the newest month, open by default
        else:
            self.opened_months.add(month)
        self.fill_sidebar()

    def click_idea(self, name):
        """Click on an idea in the sidebar: open/close it, select it, fly to its star."""
        if self.linking and self.linking != name:
            self.finish_link(name)
            return
        if name in self.open_ideas:
            # An open idea closes on the first click, whatever is selected.
            # (Before, it had to be open AND selected, so an idea that had
            # opened by itself took two clicks to close.)
            self.open_ideas.discard(name)
        else:
            self.open_ideas.add(name)
            self.mark_opened(name)
            self.fly_to(name)
        self.selected = name
        self.fill_sidebar()
        self.draw_marks()

    def go_to(self, name):
        """Select an idea, open it (and its month folder), scroll to it, fly to it."""
        self.reveal_in_sidebar(name)
        self.fly_to(name)

    def reveal_in_sidebar(self, name):
        idea = self.idea(name)
        if idea is None:
            return
        self.selected = name
        if name not in self.open_ideas:
            self.open_ideas.add(name)
            self.mark_opened(name)
        self.closed_months.discard(name[:7])
        self.opened_months.add(name[:7])
        self.fill_sidebar()
        if name in self.idea_rows:
            self.tree.scroll_to(self.idea_rows[name])
        self.draw_marks()

    def mark_opened(self, name):
        """Remember when an idea was opened: busy ideas shine brighter."""
        self.store.mark_opened(name)
        self.stamp = file_stamp(self.store.path)
        self.refresh_brightness()

    def start_edit(self, name):
        self.editing, self.editing_note = name, None
        self.fill_sidebar()

    def start_note_edit(self, note):
        self.editing, self.editing_note = None, note["created"]
        self.fill_sidebar()

    def finish_note_edit(self, parent, note, text):
        text = text.strip()
        if text:
            self.store.edit_note(parent, note["created"], text)
        self.after_change()

    def cancel_edits(self):
        self.editing = self.editing_note = None
        self.fill_sidebar()

    def delete_idea(self, name):
        """Move an idea to the Trash. No question needed: it can be restored for 30 days."""
        title = title_and_text(self.idea(name))[0] or "(no title)"
        self.store.delete_idea(name)
        self.open_ideas.discard(name)
        if self.selected == name:
            self.selected = None
        self.after_change()
        self.flash(f"“{title[:30]}” moved to the Trash (bottom of the list)")

    def delete_note(self, parent, note):
        if messagebox.askyesno("Delete note", f"Delete this note?\n\n“{note['text'][:80]}”",
                               icon="warning", parent=self.root):
            self.store.delete_note(parent, note["created"])
            self.after_change()

    def start_link(self, name):
        """Link mode: the next star (or sidebar idea) you click gets linked to this one."""
        self.linking = name
        self.update_topbar()

    def finish_link(self, other):
        a, self.linking = self.linking, None
        if a and other and a != other:
            self.store.add_link(a, other)
            self.after_change()
        else:
            self.update_topbar()

    def unlink(self, a, b):
        self.store.remove_link(a, b)
        self.after_change()

    def after_change(self):
        """After any edit: rebuild the sidebar, the galaxy and the search results."""
        self.editing = self.editing_note = None
        self.stamp = file_stamp(self.store.path)
        self.build_scene()
        self.fill_sidebar()
        self.update_results()
        self.update_topbar()
        self.request_sharp()

    def new_idea(self):
        """Press the capture shortcut for the user: the background Protostar opens its note."""
        _, mods, vk = settings.hotkey_spec(SETTINGS.get("capture_hotkey"), "ctrl_alt_i")
        # Windows' key codes for the extra keys: 0x11 = Ctrl, 0x12 = Alt, 0x10 = Shift.
        keys = [k for bit, k in ((2, 0x11), (1, 0x12), (4, 0x10)) if mods & bit] + [vk]
        user32 = ctypes.WinDLL("user32")
        for key in keys:                        # press them all down...
            user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys):              # ...and let go again
            user32.keybd_event(key, 0, 2, 0)

    # ------------------------------------------------------------------
    # Right: search
    # ------------------------------------------------------------------
    def build_search_panel(self):
        panel = tk.Frame(self.root, bg=PANEL_BG, width=PANEL_WIDTH)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        tk.Frame(self.root, bg=EDGE, width=1).pack(side="right", fill="y")

        tk.Label(panel, text="Search", bg=PANEL_BG, fg=TEXT, font=(FONT_BOLD, 12),
                 anchor="w", padx=18, pady=16).pack(fill="x")
        # StringVar: a value Tkinter can watch; "trace" calls us whenever it changes.
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.update_results())
        box = text_input(panel, font_size=10, bg=PANEL_BG)
        box.pack(fill="x", padx=14)
        self.search = box.field
        self.search.config(textvariable=self.query)
        self.search.bind("<Escape>", lambda e: self.query.set(""))
        hint = tk.Label(panel, text="Search titles, text, notes and #tags  ·  Ctrl+F", bg=PANEL_BG,
                        fg=DIM_TEXT, font=(FONT, 8), anchor="w", padx=18)
        hint.pack(fill="x", pady=(4, 0))

        self.results = ScrollArea(panel, PANEL_BG)
        self.results.pack(fill="both", expand=True, padx=8, pady=12)
        self.update_results()

    def update_results(self):
        self.results.clear()
        words = self.query.get().lower().split()
        if not words:
            self.set_matches(None)
            self.show_tags()
            return
        found = 0
        matched = set()
        for idea in reversed(self.chronological()):            # newest first
            title, text = title_and_text(idea)
            notes = " ".join(n["text"] for n in self.store.notes_of(idea))
            haystack = (title + " " + text + " " + notes).lower()
            if all(word in haystack for word in words):        # every word must appear
                self.add_result(idea, title, text + " " + notes, words[0])
                matched.add(idea["created"])
                found += 1
        if not found:
            tk.Label(self.results.inner, text="No ideas match.", bg=PANEL_BG, fg=DIM_TEXT,
                     font=(FONT, 10), anchor="w", padx=10).pack(fill="x")
        self.set_matches(matched)

    def set_matches(self, matched):
        """Light up the stars of the ideas the search found (None = not searching)."""
        if matched == self.matches:
            return
        self.matches = matched
        if hasattr(self, "scene"):            # (not yet while the window is being built)
            self.update_highlights()
            self.request_sharp()

    def show_tags(self):
        """
        With an empty search box: your #tags as small rounded pills. Write
        #something in an idea or a note to make a tag; click a pill to see
        all ideas with that tag.
        """
        tags = self.store.tags()
        if not tags:
            tk.Label(self.results.inner, text=TAGS_TIP, bg=PANEL_BG, fg=DIM_TEXT,
                     font=(FONT, 9), anchor="w", justify="left", padx=10).pack(fill="x")
            return
        tk.Label(self.results.inner, text="TAGS", bg=PANEL_BG, fg=DIM_TEXT, font=(FONT, 7),
                 anchor="w", padx=10).pack(fill="x", pady=(0, 6))
        line, used = None, 0
        measure = tkfont.Font(font=(FONT, 9)).measure
        for tag, count in tags[:30]:
            width = measure(f"●  #{tag}  {count}") + 26
            if line is None or used + width > PANEL_WIDTH - 40:
                line = tk.Frame(self.results.inner, bg=PANEL_BG)
                line.pack(fill="x", padx=8, pady=2)
                used = 0
            pill = widgets.Row(line, PANEL_BG, lambda t=tag: self.query.set("#" + t), height=24, radius=12,
                               hover=ROW_SELECTED, selected_colour=ROW_HOVER, selected=True, padx=11)
            pill.configure(width=width)
            pill.add("●", font=(FONT, 7), colour=hex_colour(soft_colour(tag)), gap=5)
            pill.add(f"#{tag}", font=(FONT, 9), colour=SOFT_TEXT, gap=5)
            pill.add(str(count), font=(FONT, 8), colour=DIM_TEXT)
            pill.pack(side="left", padx=(0, 6))
            used += width + 6

    def add_result(self, idea, title, text, word):
        name = idea["created"]
        card = row(self.results.inner, lambda: self.go_to(name), bg=PANEL_BG, height=34)
        card.pack(fill="x", pady=1)
        text = text.strip()
        card.add_line(title or "(no title)", font=(FONT, 10), colour=TEXT, gap=0)
        if text:
            # A short piece of the text around the first matching word.
            flat = text.replace("\n", " ")
            at = max(0, flat.lower().find(word) - 30)
            snippet = ("…" if at else "") + flat[at:at + 90] + ("…" if len(flat) > at + 90 else "")
            card.add_line(snippet, font=(FONT, 9), colour=DIM_TEXT, gap=3)

    # ------------------------------------------------------------------
    # Middle: top bar, timeline, galaxy
    # ------------------------------------------------------------------
    def build_middle(self):
        middle = tk.Frame(self.root, bg=g3d.SPACE_HEX)
        middle.pack(side="left", fill="both", expand=True)

        # --- Top bar ---
        top = tk.Frame(middle, bg=TOPBAR_BG, height=40)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.stats_label = tk.Label(top, bg=TOPBAR_BG, fg=DIM_TEXT, font=(FONT, 9), padx=16)
        self.stats_label.pack(side="left")
        self.hint_label = tk.Label(top, bg=TOPBAR_BG, fg=ACCENT, font=(FONT, 9))
        self.hint_label.pack(side="left", padx=10)
        self.timeline_button = small_button(top, "Timeline", self.toggle_timeline, bg=TOPBAR_BG)
        self.timeline_button.pack(side="right", padx=(8, 16))
        small_button(top, "Overview", self.overview, bg=TOPBAR_BG).pack(side="right", padx=8)
        small_button(top, "Rediscover", self.rediscover, bg=TOPBAR_BG).pack(side="right", padx=8)
        small_button(top, "Export", self.export, bg=TOPBAR_BG).pack(side="right", padx=8)
        small_button(top, "Stats", self.toggle_stats, bg=TOPBAR_BG).pack(side="right", padx=8)
        small_button(top, "Calendar", self.toggle_calendar, bg=TOPBAR_BG).pack(side="right", padx=8)
        small_button(top, "Settings", self.open_settings, bg=TOPBAR_BG).pack(side="right", padx=8)
        tk.Frame(middle, bg=EDGE, height=1).pack(fill="x")

        # --- Timeline row (hidden until "Timeline" is clicked) ---
        self.timeline_row = tk.Frame(middle, bg=TOPBAR_BG)
        self.play_button = small_button(self.timeline_row, "▶  Play", self.play_timeline,
                                        colour=SOFT_TEXT, bg=TOPBAR_BG)
        self.play_button.pack(side="left", padx=(16, 10), pady=6)
        self.timeline_date = tk.Label(self.timeline_row, bg=TOPBAR_BG, fg=SOFT_TEXT,
                                      font=(FONT, 9), width=24, anchor="w")
        self.timeline_date.pack(side="right", padx=(10, 16))
        # A Scale is a slider. `command` is called whenever it moves.
        self.slider = tk.Scale(self.timeline_row, from_=1, to=1, orient="horizontal",
                               showvalue=False, bg=TOPBAR_BG, troughcolor=INPUT_BG,
                               highlightthickness=0, borderwidth=0, sliderrelief="flat",
                               activebackground=ACCENT, command=self.on_slider)
        self.slider.pack(side="left", fill="x", expand=True, pady=6)

        # --- The galaxy, drawn by the graphics card (see galaxy_gl.py) ---
        self.view = galaxy_gl.GalaxyGL(middle, takefocus=1)
        self.view.pack(fill="both", expand=True)
        self.canvas = self.view            # the old name, still used in a few places
        c = self.view
        c.bind("<Configure>", lambda e: self.request_sharp(), add="+")
        # Mouse (like Roblox Studio):
        c.bind("<MouseWheel>", self.on_wheel)                 # fly towards / away from the pointer
        c.bind("<ButtonPress-1>", lambda e: self.on_press(e, "orbit"))
        c.bind("<B1-Motion>", self.on_drag)                   # circle around what you look at
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<ButtonPress-3>", lambda e: self.on_press(e, "look"))
        c.bind("<B3-Motion>", self.on_drag)                   # turn your head
        c.bind("<ButtonRelease-3>", self.on_release)
        c.bind("<ButtonPress-2>", lambda e: self.on_press(e, "pan"))
        c.bind("<B2-Motion>", self.on_drag)                   # slide sideways
        c.bind("<ButtonRelease-2>", self.on_release)
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", lambda e: self.set_hover(None))
        # Keyboard (only while the galaxy has the focus — click it once):
        c.bind("<KeyPress>", self.on_key_down)
        c.bind("<KeyRelease>", self.on_key_up)
        c.bind("<FocusOut>", lambda e: self.keys.clear())
        self.root.bind("<Escape>", self.on_escape, add="+")
        # Keyboard shortcuts: Ctrl+F = search, Ctrl+N = new idea.
        self.root.bind("<Control-f>", lambda e: (self.search.focus_set(), self.search.select_range(0, "end")))
        self.root.bind("<Control-n>", lambda e: self.new_idea())
        # The small label with a star's title. It's a normal Tkinter label
        # floating on top of the galaxy, moved next to the star under the mouse.
        self.hover_label = tk.Label(middle, bg=CARD_BG, fg=CARD_TEXT, font=(FONT, 10), padx=9, pady=4,
                                    highlightthickness=1, highlightbackground=CARD_EDGE)

    def update_topbar(self):
        links = len(self.store.links)
        self.stats_label.config(text=f"{len(self.ideas)} ideas   ·   {links} link{'s' if links != 1 else ''}")
        if self.linking:
            title = title_and_text(self.idea(self.linking) or {"text": ""})[0]
            self.hint_label.config(text=f"Click a star or an idea to link it with “{title[:30]}”   ·   Esc to cancel")
        else:
            self.hint_label.config(text="")

    def flash(self, message, ms=4000):
        """Show a short message in the top bar for a few seconds."""
        self.hint_label.config(text=message)
        if getattr(self, "flash_job", None):
            self.root.after_cancel(self.flash_job)
        self.flash_job = self.root.after(ms, self.update_topbar)

    def rediscover(self):
        """
        Fly to an idea you haven't touched in a long time: one of the five
        "dimmest" (least recently active), chosen at random, so old ideas
        get a second chance instead of being forgotten.
        """
        if not self.ideas:
            return
        quiet = sorted(self.ideas, key=self.store.activity)[:5]
        idea = random.choice(quiet)
        when = datetime.fromisoformat(self.store.activity(idea))
        self.go_to(idea["created"])
        self.flash(f"Rediscovered: “{title_and_text(idea)[0][:30]}” — untouched since {when:%d %b %Y}")

    def export(self):
        """Write all ideas into a readable Markdown file and show it in File Explorer."""
        target = self.store.export_markdown()
        self.flash(f"Exported to {target.name}")
        os.startfile(target.parent)        # opens the folder in File Explorer

    def overview(self):
        """Back to the view of all the ideas."""
        self.fit_camera(keep_current=True)
        self.glide = 5.0
        self.start_animation()

    def on_escape(self, event):
        if self.linking:
            self.linking = None
            self.update_topbar()

    # --- Timeline ---
    def toggle_timeline(self):
        """Show or hide the timeline: replay how your galaxy grew."""
        if self.timeline is None and self.ideas:
            self.timeline_row.pack(fill="x", before=self.canvas)
            self.slider.config(to=len(self.ideas))
            self.slider.set(len(self.ideas))
            self.timeline = len(self.ideas)
            self.timeline_button.config(fg=ACCENT)
            self.on_slider(len(self.ideas))
        else:
            self.stop_playing()
            self.timeline_row.pack_forget()
            self.timeline = None
            self.timeline_button.config(fg=DIM_TEXT)
            self.build_scene()
            self.request_sharp()

    def on_slider(self, value):
        """The slider moved: show only the first `value` ideas (by date)."""
        if self.timeline is None:
            return
        self.timeline = int(float(value))
        ideas = self.chronological()
        last = ideas[self.timeline - 1]["created"]
        self.timeline_date.config(text=f"{datetime.fromisoformat(last).strftime('%d %b %Y')}   ·   "
                                       f"{self.timeline} of {len(ideas)}")
        self.build_scene()
        self.render(moving=self.playing is not None)

    def play_timeline(self):
        if self.playing:
            self.stop_playing()
            return
        if self.timeline is None:
            self.toggle_timeline()
        self.slider.set(1)
        self.play_button.config(text="❚❚  Pause")
        # The whole replay takes about 8 seconds, whatever the number of ideas.
        self.play_step = max(1, len(self.ideas) // 160)
        self.playing = self.root.after(50, self.play_next)

    def play_next(self):
        value = min(len(self.ideas), self.timeline + self.play_step)
        self.slider.set(value)
        if value < len(self.ideas):
            self.playing = self.root.after(50, self.play_next)
        else:
            self.stop_playing()

    def stop_playing(self):
        if self.playing:
            self.root.after_cancel(self.playing)
        self.playing = None
        self.play_button.config(text="▶  Play")
        self.request_sharp()

    # --- Building the galaxy from the ideas ---
    def build_scene(self):
        """
        Turn the ideas into a galaxy scene and send it to the graphics card.
        With the timeline on, only the ideas up to the slider's date are included.
        """
        ideas = self.chronological()
        if self.timeline is not None:
            ideas = ideas[:self.timeline]
        self.shown = [i["created"] for i in ideas]          # scene number -> name tag
        self.scene_number = {name: n for n, name in enumerate(self.shown)}
        slots = [i["slot"] for i in ideas]
        # Linked ideas gather into clusters (see galaxy3d.cluster_positions).
        pairs = [(self.scene_number[a], self.scene_number[b]) for a, b in
                 (l["link"] for l in self.store.links)
                 if a in self.scene_number and b in self.scene_number]
        positions = g3d.cluster_positions(slots, pairs, spacing=CLUSTER_SPACING)
        # Each constellation (group of linked ideas) gets its own soft colour,
        # chosen from its oldest idea so it never changes.
        groups = g3d.link_groups(len(slots), pairs)
        oldest = {}
        for n, group in enumerate(groups):
            if group not in oldest or slots[n] < slots[oldest[group]]:
                oldest[group] = n
        self.group_colour = [soft_colour(self.shown[oldest[group]]) for group in groups]
        self.scene = g3d.Scene(slots, [colour_index(i) for i in ideas],
                               [len(self.store.notes_of(i)) for i in ideas],
                               [glow_from_activity(self.store.activity(i)) for i in ideas],
                               positions=positions)
        self.hovered = None
        self.view.set_scene(self.scene)
        self.update_highlights()

    def refresh_brightness(self):
        """Update only how bright each star is (cheaper than rebuilding the scene)."""
        brightness = []
        for name in self.shown:
            idea = self.idea(name)
            brightness.append(glow_from_activity(self.store.activity(idea)) if idea else 0.45)
        self.scene.brightness = brightness
        self.update_highlights()
        self.request_sharp()

    def update_highlights(self):
        """
        Tell the graphics card how each star should look right now: its
        colour and size (from its life stage), how bright it is (activity),
        and the constellation highlight when you hover a star — the star and
        all the stars linked to it light up, and so do their lines.
        """
        hovered = self.shown[self.hovered] if self.hovered is not None else None
        focus = hovered or self.selected
        partners = set()
        if focus and self.idea(focus):
            partners = {o["created"] for o in self.store.linked_to(self.idea(focus))}
        tints, bright, scales = [], [], []
        birth = self.birth_factor()
        for n, name in enumerate(self.shown):
            idea = self.idea(name) or {}
            stage = idea.get("stage", "spark")
            tint = STAGE_TINT.get(stage) or self.star_tint(idea, n)
            b = self.scene.brightness[n]
            scale = STAGE_SCALE.get(stage, 1.0)
            if idea.get("pinned"):
                b, scale = max(b, 0.95), scale * 1.15     # pinned ideas never fade
            if self.matches is not None:
                b *= 1.4 if name in self.matches else 0.22   # searching: matches shine, others dim
            if name == hovered:
                b *= 1.7
            elif name in partners:
                b *= 1.5                      # the constellation lights up
            if birth and name == birth[0]:
                b *= birth[1]
                scale *= birth[2]
            tints.append(tint)
            bright.append(b)
            scales.append(scale)
        note_tints = self.scene.note_light / 110 * 255 if len(self.scene.notes) else None
        self.view.set_stars(self.scene.ideas, tints, bright, scales, self.scene.notes, note_tints)
        # Constellation lines.
        segments, alphas, colours = [], [], []
        for link in self.store.links:
            a, b = (self.scene_number.get(x) for x in link["link"])
            if a is None or b is None:
                continue
            segments.append((self.scene.ideas[a], self.scene.ideas[b]))
            colours.append(self.group_colour[a])
            if focus and focus in link["link"]:
                alphas.append(0.85)
            elif self.matches is not None:
                both = link["link"][0] in self.matches and link["link"][1] in self.matches
                alphas.append(0.5 if both else 0.05)
            else:
                alphas.append(0.14 if focus else 0.32)   # others fade a bit while one is lit
        # The selected idea's notes: thin, faint lines from each note to its idea
        # (only while the idea is selected, so the galaxy stays clean otherwise).
        chosen = self.scene_number.get(self.selected)
        if chosen is not None:
            for i, parent in enumerate(self.scene.note_parent):
                if parent == chosen:
                    segments.append((self.scene.notes[i], self.scene.ideas[chosen]))
                    alphas.append(0.28)
                    colours.append((170, 180, 200))
        self.view.set_lines(segments, alphas, colours)
        n = self.scene_number.get(self.selected)
        self.view.set_ring(self.scene.ideas[n] if n is not None else None)

    # --- A star is born (the animation when a new idea arrives) ---
    BIRTH_SECONDS = 1.6

    def start_birth(self, name):
        """A new idea's star ignites: it flares up bright and big, then settles."""
        if not SETTINGS["animations"]:
            return
        self.birth = (name, time.perf_counter())
        self.birth_step()

    def birth_factor(self):
        """(name, brightness factor, size factor) while a star is being born, else None."""
        if not self.birth:
            return None
        name, start = self.birth
        t = (time.perf_counter() - start) / self.BIRTH_SECONDS
        if t >= 1:
            return None
        # Grows from nothing, flashes at about 1/4 of the way, then calms down.
        flash = math.exp(-((t - 0.25) / 0.18) ** 2)
        return name, 0.2 + 0.8 * min(1, t * 4) + 2.5 * flash, min(1, t * 3) * (1 + 1.2 * flash)

    def birth_step(self):
        """One frame of the birth animation (about 60 per second, for 1.6 seconds)."""
        done = self.birth_factor() is None
        if done:
            self.birth = None
        self.update_highlights()
        if self.anim is None:
            self.render()
        if not done:
            self.root.after(16, self.birth_step)

    def star_tint(self, idea, n):
        """A star's colour: natural star colours, or (Settings) the colour of its first #tag."""
        if SETTINGS["star_colours"] == "tags":
            words = " ".join([title_and_text(idea)[0], title_and_text(idea)[1]]
                             + [x["text"] for x in self.store.notes_of(idea)]).lower()
            tags = TAG.findall(words)
            if tags:
                return soft_colour(tags[0])
        return self.scene.idea_colours[n]

    def view_size(self):
        return max(1, self.view.winfo_width()), max(1, self.view.winfo_height())

    def fit_camera(self, keep_current=False):
        """A view of all the ideas, from above at an angle."""
        if self.scene.count:
            pts = self.scene.ideas.astype(np.float64)
            centre = pts.mean(axis=0)
            spread = float(np.max(np.linalg.norm(pts - centre, axis=1)))
        else:
            centre, spread = np.zeros(3), 0.6
        self.pivot = centre
        self.goal = g3d.Camera(yaw=0.0, pitch=-0.8)
        self.goal.look_at(centre, 1.6 * max(0.10, spread))
        if not keep_current:
            self.camera = self.goal.copy()
        self.fitted = True

    # --- Drawing ---
    def render(self, moving=False):
        """Ask the graphics card to draw the current view (takes a few milliseconds)."""
        w, h = self.view_size()
        if w < 10 or h < 10:
            return
        if not self.fitted:
            self.fit_camera()
        self.view.camera = self.camera
        self.view.draw()
        # Where each idea's star is on screen (for hovering and clicking).
        if self.scene.count:
            sx, sy, depth, _ = self.camera.project(self.scene.ideas, w, h)
            self.screen = np.stack([sx, sy], axis=1)
            self.visible = (depth > 0.01) & (sx > -10) & (sx < w + 10) & (sy > -10) & (sy < h + 10)
        else:
            self.screen, self.visible = np.zeros((0, 2)), np.zeros(0, bool)
        self.place_hover_label()

    def request_sharp(self):
        """Draw a picture soon (unless the animation is running: it will)."""
        if self.anim is None:
            if self.sharp_pending:
                self.root.after_cancel(self.sharp_pending)
            self.sharp_pending = self.root.after(15, self.sharp_now)

    def sharp_now(self):
        self.sharp_pending = None
        if self.anim is None:
            self.render()

    def draw_marks(self):
        """Selection or links changed: update the highlights and redraw."""
        self.update_highlights()
        self.request_sharp()

    def place_hover_label(self):
        """Put the title label next to the star under the mouse (or hide it)."""
        n = self.hovered
        if n is None or n >= len(self.visible) or not self.visible[n]:
            self.hover_label.place_forget()
            return
        title = title_and_text(self.idea(self.shown[n]) or {"text": ""})[0] or "(no title)"
        self.hover_label.config(text=title if len(title) <= 50 else title[:49] + "…")
        x, y = self.screen[n]
        self.hover_label.place(in_=self.view, x=int(x) + 14, y=int(y) - 34)
        self.hover_label.lift()

    def star_at(self, x, y):
        """The scene number of the star closest to (x, y), if within 12 pixels."""
        if not len(self.screen):
            return None
        d = np.hypot(self.screen[:, 0] - x, self.screen[:, 1] - y)
        d[~self.visible] = np.inf
        n = int(np.argmin(d))
        return n if d[n] <= 12 else None

    def set_hover(self, n):
        if n != self.hovered:
            self.hovered = n
            self.view.config(cursor="hand2" if n is not None or self.linking else "")
            self.update_highlights()
            if self.anim is None:
                self.render()
            else:
                self.place_hover_label()

    # --- The animation loop ---
    def start_animation(self):
        """Start the loop that glides `camera` towards `goal` (if it isn't running)."""
        if self.anim is None:
            self.last_tick = time.perf_counter()
            self.anim = self.root.after(0, self.tick)

    def tick(self):
        """
        One animation frame. It keeps going only while the camera is still
        moving or a movement key is held; then it stops, and the app goes
        back to using no CPU at all.
        """
        now = time.perf_counter()
        dt = min(0.05, now - self.last_tick)
        self.last_tick = now
        if self.keys:
            self.move_with_keys(dt)
        # Glide part of the way to the goal. 1 - e^(-speed*dt) is the same
        # smooth "catch up" no matter how fast or slow the computer draws.
        k = 1.0 - math.exp(-self.glide * dt)
        cam, goal = self.camera, self.goal
        cam.position += (goal.position - cam.position) * k
        cam.yaw += (goal.yaw - cam.yaw) * k
        cam.pitch += (goal.pitch - cam.pitch) * k
        self.render(moving=True)
        gap = (np.linalg.norm(goal.position - cam.position)
               / max(1e-6, np.linalg.norm(cam.position - self.pivot)))
        settled = gap < 1e-3 and abs(goal.yaw - cam.yaw) < 1e-4 and abs(goal.pitch - cam.pitch) < 1e-4
        if self.keys or self.dragged or not settled:
            self.anim = self.root.after(8, self.tick)
        else:
            self.camera = self.goal.copy()
            self.anim = None
            self.glide = 12.0
            self.render(moving=False)            # the final, sharp picture

    # --- Mouse ---
    def on_motion(self, event):
        self.set_hover(self.star_at(event.x, event.y))

    def on_press(self, event, mode):
        self.canvas.focus_set()                  # so the keyboard moves the galaxy
        self.mode = mode
        self.last = (event.x, event.y)
        self.press = (event.x, event.y)
        self.dragged = False
        self.glide = 12.0
        if mode == "orbit":
            # Circle around the point straight ahead, as far away as the
            # current pivot: re-aiming it avoids a jump if you looked around.
            distance = np.linalg.norm(self.pivot - self.goal.position)
            self.pivot = self.goal.position + self.goal.forward() * distance

    def on_drag(self, event):
        dx, dy = event.x - self.last[0], event.y - self.last[1]
        self.last = (event.x, event.y)
        if abs(event.x - self.press[0]) + abs(event.y - self.press[1]) > 3:
            self.dragged = True
        if not self.dragged:
            return
        goal = self.goal
        limit = math.radians(89)
        if self.mode == "orbit":
            distance = np.linalg.norm(self.pivot - goal.position)
            goal.yaw += dx * 0.005
            goal.pitch = min(limit, max(-limit, goal.pitch + dy * 0.005))
            goal.look_at(self.pivot, distance)
        elif self.mode == "look":
            goal.yaw += dx * 0.0035
            goal.pitch = min(limit, max(-limit, goal.pitch - dy * 0.0035))
        else:  # pan
            _, right, up, _ = goal.basis()
            w, h = self.view_size()
            per_pixel = np.linalg.norm(self.pivot - goal.position) / g3d.focal_length(w, h)
            shift = -right * dx * per_pixel + up * dy * per_pixel
            goal.position += shift
            self.pivot = self.pivot + shift
        self.set_hover(None)
        self.start_animation()

    def on_release(self, event):
        if not self.dragged and self.mode == "orbit":
            n = self.star_at(event.x, event.y)
            if n is not None and self.linking:
                self.finish_link(self.shown[n])
            elif n is not None:
                self.reveal_in_sidebar(self.shown[n])
            elif not self.linking:
                self.selected = None
                self.draw_marks()
        self.dragged = False

    def distance_under_pointer(self, x, y, direction):
        """How far away the thing under the mouse pointer is."""
        n = self.star_at(x, y)
        if n is not None:                        # a star: its exact distance
            return float(np.linalg.norm(self.scene.ideas[n] - self.goal.position)), n
        pos = self.goal.position
        # Otherwise: where the pointer's line hits the galaxy's flat plane (z = 0)...
        if abs(direction[2]) > 1e-6:
            t = -pos[2] / direction[2]
            if 0 < t < 4 * max(0.2, np.linalg.norm(pos)):
                return float(t), None
        # ...or, if it misses the plane, the distance to the galaxy's centre.
        return float(max(0.05, np.linalg.norm(pos))), None

    def on_wheel(self, event):
        """
        Roblox-style zoom: scrolling flies the camera along the line from
        your eye through the mouse pointer. Point at something and scroll:
        you fly towards it. Each step covers a fixed share of the distance,
        so it's quick from far away and gentle up close.
        """
        w, h = self.view_size()
        direction = self.goal.ray(event.x, event.y, w, h)
        distance, star = self.distance_under_pointer(event.x, event.y, direction)
        if event.delta > 0:                       # scroll up: forward
            step = 0.22 * distance
            if star is not None:
                step = min(step, distance - 0.004)    # don't fly through the star
        else:                                     # scroll down: back
            step = -0.28 * distance
        self.goal.position = self.goal.position + direction * step
        # Left-drag will now circle around what you pointed at.
        self.pivot = self.goal.position + direction * max(0.004, distance - step)
        self.glide = 10.0
        self.start_animation()

    # --- Keyboard: fly like in Roblox Studio ---
    MOVE_KEYS = {"w", "a", "s", "d", "q", "e"}

    def on_key_down(self, event):
        key = event.keysym.lower()
        if key in self.MOVE_KEYS:
            self.keys.add(key)
            self.start_animation()
        elif key in ("shift_l", "shift_r"):
            self.keys.add("shift")
        elif key == "f" and self.selected is not None:
            self.fly_to(self.selected)                 # F = focus on the selected star
        elif key == "home":
            self.overview()

    def on_key_up(self, event):
        key = event.keysym.lower()
        self.keys.discard("shift" if key.startswith("shift") else key)

    def move_with_keys(self, dt):
        """W/S forward/back, A/D left/right, E/Q up/down. Hold Shift to go faster."""
        _, right, _, forward = self.goal.basis()
        move = np.zeros(3)
        move += forward * (("w" in self.keys) - ("s" in self.keys))
        move += right * (("d" in self.keys) - ("a" in self.keys))
        move += np.array([0, 0, 1.0]) * (("e" in self.keys) - ("q" in self.keys))
        if not move.any():
            return
        # Speed depends on how far you are from the galaxy: fast when far
        # away, slow among the stars.
        speed = 0.5 * max(0.04, min(3.0, np.linalg.norm(self.goal.position)))
        if "shift" in self.keys:
            speed *= 3
        step = move / np.linalg.norm(move) * speed * dt
        self.goal.position = self.goal.position + step
        self.pivot = self.pivot + step

    # --- Flying the camera to a star ---
    def fly_to(self, name):
        """Glide the camera towards an idea's star, keeping the same viewing angle."""
        n = self.scene_number.get(name)
        if n is None:
            return
        star = self.scene.ideas[n].astype(np.float64)
        distance = min(0.12, float(np.linalg.norm(star - self.goal.position)))
        self.goal.look_at(star, max(0.03, distance))
        self.pivot = star
        # A calm flight — or, with animations off in Settings, an almost instant jump.
        self.glide = 4.0 if SETTINGS["animations"] else 60.0
        self.start_animation()

    # ------------------------------------------------------------------
    # Changes made elsewhere (the capture note)
    # ------------------------------------------------------------------
    def check_open_request(self):
        """A reminder pop-up's "Open" button asks us (with a small file) to show an idea."""
        request = self.store.path.parent / "open_request.json"
        try:
            if time.time() - request.stat().st_mtime < 30:
                name = json.loads(request.read_text(encoding="utf-8")).get("idea")
                if self.idea(name):
                    self.go_to(name)
                    self.root.deiconify()
                    self.root.lift()
            request.unlink()
        except (FileNotFoundError, ValueError):
            pass

    def check_for_changes(self):
        """
        Runs once a second. If ideas.jsonl changed (you saved an idea or a
        note with Ctrl+Alt+I), reload, rebuild the galaxy and go to it.
        """
        if file_stamp(self.store.path) != self.stamp and not self.editing and not self.editing_note:
            before = {i["created"] for i in self.ideas}
            notes_before = sum(len(v) for v in self.store.notes.values())
            self.store.load()
            self.stamp = file_stamp(self.store.path)
            new = [i["created"] for i in self.ideas if i["created"] not in before]
            if self.timeline is not None:
                self.toggle_timeline()             # leave the timeline: show everything
            self.after_change()
            if new:
                self.go_to(max(new))
                self.start_birth(max(new))
            elif sum(len(v) for v in self.store.notes.values()) > notes_before:
                # A note was added from the capture note: open its idea.
                newest = max((n for v in self.store.notes.values() for n in v), key=lambda n: n["created"])
                self.go_to(newest["parent"])
        self.check_open_request()
        self.root.after(CHECK_EVERY_MS, self.check_for_changes)


def main():
    # "python map.py demo" opens the demo galaxy; a file name opens that file;
    # nothing opens your real ideas.
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        import demo
        path = demo.make_demo_file()
    elif len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = IDEAS_FILE
    ProtostarApp(path).root.mainloop()


if __name__ == "__main__":
    main()
