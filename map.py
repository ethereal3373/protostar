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
import math
import subprocess
import os
import random
import sys
import time
import tkinter as tk
import zlib
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

import numpy as np

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


def small_button(parent, text, command, colour=DIM_TEXT, bg=SIDEBAR_BG):
    """A little text button (like a link) that brightens when hovered."""
    return widgets.small_button(parent, text, command, colour, bg, (FONT, 9), TEXT)


def text_input(parent, value="", height=None, font_size=10, bg=SIDEBAR_BG):
    """
    A dark text field with rounded corners: one line, or several if `height`
    is given. Use `box.field` to read it (box.field.get()) or bind keys to it.
    """
    box = widgets.RoundedBox(parent, bg, fill=INPUT_BG, outline=INPUT_EDGE, focus_outline=FOCUS_EDGE,
                             kind="text" if height else "entry", lines=height or 1,
                             fg=TEXT, insertbackground=TEXT, font=(FONT, font_size),
                             selectbackground="#34405a")
    if height:
        box.field.insert("1.0", value)
    else:
        box.field.insert(0, value)
    return box


def row(parent, on_click=None, selected=False, height=30, bg=SIDEBAR_BG):
    """A clickable row with a rounded highlight (see widgets.Row)."""
    return widgets.Row(parent, bg, on_click, height=height, hover=ROW_HOVER,
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
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(960, 580)
        dark_title_bar(self.root)

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

        # "New idea": presses Ctrl+Alt+I for you, which opens the capture note
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
            tk.Label(self.tree.inner, text="No ideas yet.\nPress Ctrl+Alt+I to catch one.",
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
    # Which settings need what to restart before they show.
    RESTART_APP = {"theme", "accent", "font", "detail"}
    RESTART_BACKGROUND = {"capture_hotkey", "map_hotkey", "capture_save", "font"}

    def open_settings(self):
        """A window with all the options. Each click is saved right away."""
        if getattr(self, "settings_window", None) and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("Protostar settings")
        win.configure(bg=SIDEBAR_BG)
        win.geometry(f"560x700+{self.root.winfo_x() + 120}+{self.root.winfo_y() + 60}")
        win.transient(self.root)
        dark_title_bar(win)
        self.settings_window = win
        self.pending = getattr(self, "pending", set())
        area = ScrollArea(win, SIDEBAR_BG)
        area.pack(fill="both", expand=True, padx=12, pady=12)
        self.settings_area = area
        self.fill_settings()

    def fill_settings(self):
        area = self.settings_area
        area.clear()
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
                chosen = SETTINGS.get(key) == value
                pill = widgets.Row(line, SIDEBAR_BG, lambda v=value: self.change_setting(key, v),
                                   height=26, radius=13, hover=ROW_HOVER,
                                   selected_colour=_T["growing"] if chosen else ROW_SELECTED,
                                   selected=True, padx=12)
                pill.configure(width=measure(name) + 26)
                pill.add(name, font=(FONT, 9), colour=ACCENT if chosen else SOFT_TEXT)
                pill.pack(side="left", padx=(0, 6))

        section("Look")
        option("Theme", "The colours of the panels. The galaxy itself is always space-black.", "theme",
               [(k, v["name"]) for k, v in settings.THEMES.items()])
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
        option("Shortcut: new idea", "If a shortcut doesn't work, another program may already use it.",
               "capture_hotkey", [(k, settings.HOTKEYS[k][0]) for k in settings.CAPTURE_HOTKEYS])
        option("Shortcut: open the galaxy", None, "map_hotkey",
               [(k, settings.HOTKEYS[k][0]) for k in settings.MAP_HOTKEYS])
        option("Saving", "Which key saves the idea, and which one starts a new line.", "capture_save",
               [("enter", "Enter saves"), ("ctrl_enter", "Ctrl+Enter saves")])

        section("System")
        box = tk.Frame(inner, bg=SIDEBAR_BG)
        box.pack(fill="x", padx=8, pady=(4, 6))
        tk.Label(box, text="Start with Windows", bg=SIDEBAR_BG, fg=TEXT, font=(FONT, 10), anchor="w").pack(fill="x")
        line = tk.Frame(box, bg=SIDEBAR_BG)
        line.pack(fill="x", pady=(5, 0))
        on = startup.is_installed()
        for value, name in ((True, "On"), (False, "Off")):
            chosen = on == value
            pill = widgets.Row(line, SIDEBAR_BG, lambda v=value: self.set_autostart(v), height=26, radius=13,
                               hover=ROW_HOVER, selected_colour=_T["growing"] if chosen else ROW_SELECTED,
                               selected=True, padx=12)
            pill.configure(width=tkfont.Font(font=(FONT, 9)).measure(name) + 26)
            pill.add(name, font=(FONT, 9), colour=ACCENT if chosen else SOFT_TEXT)
            pill.pack(side="left", padx=(0, 6))

        if self.pending:
            tk.Frame(inner, bg=EDGE, height=1).pack(fill="x", padx=8, pady=(18, 10))
            tk.Label(inner, text="Some changes need Protostar to restart.", bg=SIDEBAR_BG, fg=SOFT_TEXT,
                     font=(FONT, 9), anchor="w", padx=8).pack(fill="x")
            restart = row(inner, self.restart_protostar, height=34)
            restart.pack(fill="x", padx=4, pady=(6, 10))
            restart.add("↻", font=(FONT, 11), colour=ACCENT, gap=8)
            restart.add("Restart Protostar now", font=(FONT, 10), colour=TEXT)

    def change_setting(self, key, value):
        SETTINGS[key] = value
        settings.save(SETTINGS)
        if key in self.RESTART_APP or key in self.RESTART_BACKGROUND:
            self.pending.add(key)
        if key in ("star_colours", "animations"):       # these work right away
            self.update_highlights()
            self.request_sharp()
        self.fill_settings()

    def set_autostart(self, on):
        if on and not startup.is_installed():
            startup.make_shortcut()
        elif not on and startup.SHORTCUT.exists():
            startup.SHORTCUT.unlink()
        self.fill_settings()

    def restart_protostar(self):
        """
        Apply the settings: restart the background part (new shortcuts, keys,
        font) and reopen this window (new theme, accent, font, detail).
        """
        if self.pending & self.RESTART_BACKGROUND:
            startup.stop_running()
            startup.start_now()
        if self.pending & self.RESTART_APP:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            subprocess.Popen([pythonw, Path(__file__).resolve(), *sys.argv[1:]],
                             cwd=Path(__file__).parent)
            self.root.destroy()
            return
        self.pending.clear()
        self.fill_settings()

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
        """A small text field under an open idea: type a note and press Enter."""
        hint = "Add a note…"
        box = text_input(parent, hint, font_size=9)
        box.pack(fill="x", pady=(10, 0))
        entry = box.field
        entry.config(fg=DIM_TEXT)

        def focus_in(event):
            if entry.get() == hint:              # remove the grey hint when you click in
                entry.delete(0, "end")
                entry.config(fg=TEXT)

        def focus_out(event):
            if not entry.get():                  # put the hint back if you left it empty
                entry.insert(0, hint)
                entry.config(fg=DIM_TEXT)

        def save(event):
            text = entry.get().strip()
            if text and text != hint:
                self.store.add_note(idea["created"], text)
                self.after_change()

        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)
        entry.bind("<Return>", save)
        entry.bind("<Escape>", lambda e: self.canvas.focus_set())

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
        if name in self.open_ideas and self.selected == name:
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
        """Press Ctrl+Alt+I for the user: the background Protostar opens its note."""
        user32 = ctypes.WinDLL("user32")
        for key in (0x11, 0x12, 0x49):          # Ctrl, Alt, I down
            user32.keybd_event(key, 0, 0, 0)
        for key in (0x49, 0x12, 0x11):          # and up again
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
