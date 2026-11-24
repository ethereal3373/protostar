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
import sys
import time
import tkinter as tk
import zlib
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import numpy as np
from PIL import ImageTk  # ImageTk turns Pillow pictures into Tkinter ones

import galaxy3d as g3d
from ideas_store import Store
# Reuse the same file location and window title as the always-running part.
from protostar import IDEAS_FILE, MAP_TITLE

# --- Colours: dark, warm greys (similar to the Claude app) ---
SIDEBAR_BG = "#1f1e1d"
PANEL_BG = "#1f1e1d"
TOPBAR_BG = "#1a1918"
EDGE = "#2f2e2b"           # thin lines between areas
ROW_HOVER = "#2a2927"
ROW_SELECTED = "#34332f"
INPUT_BG = "#2a2927"
TEXT = "#eeede9"
SOFT_TEXT = "#bdbbb3"
DIM_TEXT = "#83817a"
ACCENT = "#d97757"         # a warm clay orange, used very sparingly
DANGER = "#d9776a"
LINK_LINE = "#3b4150"      # constellation lines
LINK_LINE_LIT = "#7d8597"  # lines of the selected idea
FONT = "Segoe UI"

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


class ScrollArea(tk.Frame):
    """
    A box whose contents can scroll with the mouse wheel.
    Tkinter can't scroll a Frame directly, so we put the Frame inside a
    Canvas (which can scroll) and move the canvas view. No visible scrollbar,
    to keep it clean (like the Claude app).
    """

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        # Keep the inner frame as wide as the box, and update how far it can scroll.
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        # Only scroll this box while the mouse is over it.
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self.on_wheel))
        self.bind("<Leave>", self.on_leave)

    def on_leave(self, event):
        # Tkinter also sends "Leave" when the mouse moves onto a row INSIDE the
        # box, so we check where the mouse really is before switching scrolling off.
        under = self.winfo_containing(*self.winfo_pointerxy())
        if under is None or not str(under).startswith(str(self)):
            self.unbind_all("<MouseWheel>")

    def on_wheel(self, event):
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()

    def scroll_to(self, widget):
        """Scroll so that `widget` is visible."""
        self.update_idletasks()
        total = max(1, self.inner.winfo_height())
        y = widget.winfo_y()
        h = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if y < top or y + widget.winfo_height() > top + h:
            self.canvas.yview_moveto(max(0, (y - h / 3) / total))


def make_row(parent, bg, on_click):
    """A clickable row that lights up when the mouse is over it."""
    row = tk.Frame(parent, bg=bg, cursor="hand2")

    def paint(colour):
        row.configure(bg=colour)
        for child in row.winfo_children():
            child.configure(bg=colour)

    row.normal_bg = bg
    row.bind("<Enter>", lambda e: paint(ROW_HOVER if row.normal_bg != ROW_SELECTED else ROW_SELECTED))
    row.bind("<Leave>", lambda e: paint(row.normal_bg))
    row.bind("<Button-1>", lambda e: on_click())
    return row


def bind_children(row):
    """Make clicks/hover on a row's labels behave like clicks/hover on the row."""
    for child in row.winfo_children():
        for event in ("<Button-1>", "<Enter>", "<Leave>"):
            child.bind(event, lambda e, ev=event: row.event_generate(ev, x=0, y=0))


def small_button(parent, text, command, colour=DIM_TEXT, bg=SIDEBAR_BG):
    """A little text button (like a link) that brightens when hovered."""
    label = tk.Label(parent, text=text, bg=bg, fg=colour, font=(FONT, 9), cursor="hand2")
    label.bind("<Enter>", lambda e: label.config(fg=TEXT))
    label.bind("<Leave>", lambda e: label.config(fg=colour))
    label.bind("<Button-1>", lambda e: command())
    return label


def text_input(parent, value="", height=None, font_size=10):
    """A dark text field: one line (Entry), or several lines if `height` is given (Text)."""
    style = dict(bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
                 font=(FONT, font_size), highlightthickness=1, highlightbackground=EDGE,
                 highlightcolor="#4a4945", borderwidth=4)
    if height:
        box = tk.Text(parent, height=height, wrap="word", undo=True, **style)
        box.insert("1.0", value)
    else:
        box = tk.Entry(parent, **style)
        box.insert(0, value)
    return box


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------

class ProtostarApp:
    def __init__(self, path):
        self.store = Store(path)
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
        self.editing = None           # idea being edited in the sidebar
        self.editing_note = None      # note being edited
        self.linking = None           # idea waiting for its link partner
        self.hovered = None           # scene number of the star under the mouse
        self.timeline = None          # None, or how many ideas the timeline shows

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

        tk.Label(bar, text="Protostar", bg=SIDEBAR_BG, fg=TEXT, font=(FONT + " Semibold", 15),
                 anchor="w", padx=18, pady=16).pack(fill="x")

        # "New idea": presses Ctrl+Alt+I for you, which opens the capture note
        # (if Protostar is running in the background).
        new = make_row(bar, SIDEBAR_BG, self.new_idea)
        new.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(new, text="＋", bg=SIDEBAR_BG, fg=ACCENT, font=(FONT, 12), padx=8).pack(side="left")
        tk.Label(new, text="New idea", bg=SIDEBAR_BG, fg=TEXT, font=(FONT, 10), pady=7).pack(side="left")
        bind_children(new)

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
            return
        # Group ideas by month, newest month first, newest idea first.
        months = {}
        for idea in reversed(self.chronological()):
            months.setdefault(idea["created"][:7], []).append(idea)   # "2026-11"
        for month in sorted(months, reverse=True):
            is_open = month not in self.closed_months
            name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            folder = make_row(self.tree.inner, SIDEBAR_BG, lambda m=month: self.toggle_month(m))
            folder.pack(fill="x", pady=(4, 0))
            tk.Label(folder, text="▾" if is_open else "▸", bg=SIDEBAR_BG, fg=DIM_TEXT,
                     font=(FONT, 9), width=2).pack(side="left", padx=(6, 0))
            tk.Label(folder, text=name, bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT + " Semibold", 10),
                     anchor="w", pady=6).pack(side="left")
            tk.Label(folder, text=str(len(months[month])), bg=SIDEBAR_BG, fg=DIM_TEXT,
                     font=(FONT, 9), padx=10).pack(side="right")
            bind_children(folder)
            if is_open:
                for idea in months[month]:
                    self.add_idea_row(idea)

    def add_idea_row(self, idea):
        name = idea["created"]
        title, text = title_and_text(idea)
        selected = name == self.selected
        bg = ROW_SELECTED if selected else SIDEBAR_BG
        box = tk.Frame(self.tree.inner, bg=SIDEBAR_BG)
        box.pack(fill="x")
        row = make_row(box, bg, lambda: self.click_idea(name))
        row.pack(fill="x", padx=(18, 0))
        is_open = name in self.open_ideas
        tk.Label(row, text="▾" if is_open else "▸", bg=bg, fg=DIM_TEXT, font=(FONT, 8),
                 width=2).pack(side="left", padx=(4, 0))
        notes = self.store.notes_of(idea)
        if notes:   # how many notes this idea has, in small grey numbers on the right
            tk.Label(row, text=str(len(notes)), bg=bg, fg=DIM_TEXT, font=(FONT, 8),
                     padx=8).pack(side="right")
        shown = title if len(title) <= 28 else title[:27] + "…"
        tk.Label(row, text=shown or "(no title)", bg=bg, fg=TEXT if selected else SOFT_TEXT,
                 font=(FONT, 10), anchor="w", pady=5).pack(side="left", fill="x", expand=True)
        bind_children(row)
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
                box.focus_set()
                box.bind("<Return>", lambda e, n=note, b=box: self.finish_note_edit(name, n, b.get()))
                box.bind("<Escape>", lambda e: self.cancel_edits())
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

        # Buttons: Edit · Link · Delete
        actions = tk.Frame(body, bg=SIDEBAR_BG)
        actions.pack(fill="x", pady=(10, 0))
        small_button(actions, "Edit", lambda: self.start_edit(name)).pack(side="left")
        tk.Label(actions, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(actions, "Link to…", lambda: self.start_link(name)).pack(side="left")
        tk.Label(actions, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(actions, "Delete", lambda: self.delete_idea(name), colour=DANGER).pack(side="left")

        self.add_note_box(body, idea)

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
            self.store.edit_idea(idea["created"], title_box.get().strip(),
                                 text_box.get("1.0", "end").strip())
            self.after_change()

        small_button(buttons, "Save", save, colour=ACCENT).pack(side="left")
        tk.Label(buttons, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 9)).pack(side="left", padx=6)
        small_button(buttons, "Cancel", self.cancel_edits).pack(side="left")
        title_box.focus_set()
        title_box.bind("<Return>", lambda e: save())
        title_box.bind("<Escape>", lambda e: self.cancel_edits())

    def add_note_box(self, parent, idea):
        """A small text field under an open idea: type a note and press Enter."""
        hint = "Add a note…"
        entry = tk.Entry(parent, bg=SIDEBAR_BG, fg=DIM_TEXT, insertbackground=TEXT, relief="flat",
                         font=(FONT, 9), highlightthickness=1, highlightbackground=EDGE,
                         highlightcolor="#4a4945", borderwidth=4)
        entry.insert(0, hint)
        entry.pack(fill="x", pady=(10, 0))

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
        self.closed_months ^= {month}   # ^= flips: add it if missing, remove it if present
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
        idea = self.idea(name)
        title = title_and_text(idea)[0] or "(no title)"
        extra = len(self.store.notes_of(idea))
        message = f"Delete “{title}”?"
        if extra:
            message += f"\nIts {extra} note{'s' if extra != 1 else ''} will be deleted too."
        message += "\n\nThis can't be undone."
        if messagebox.askyesno("Delete idea", message, icon="warning", parent=self.root):
            self.store.delete_idea(name)
            self.open_ideas.discard(name)
            if self.selected == name:
                self.selected = None
            self.after_change()

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

        tk.Label(panel, text="Search", bg=PANEL_BG, fg=TEXT, font=(FONT + " Semibold", 12),
                 anchor="w", padx=18, pady=16).pack(fill="x")
        box = tk.Frame(panel, bg=INPUT_BG, padx=12, pady=8)
        box.pack(fill="x", padx=14)
        tk.Label(box, text="⌕", bg=INPUT_BG, fg=DIM_TEXT, font=(FONT, 12)).pack(side="left")
        # StringVar: a value Tkinter can watch; "trace" calls us whenever it changes.
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.update_results())
        self.search = tk.Entry(box, textvariable=self.query, bg=INPUT_BG, fg=TEXT,
                               insertbackground=TEXT, relief="flat", font=(FONT, 10),
                               highlightthickness=0, borderwidth=0)
        self.search.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search.bind("<Escape>", lambda e: self.query.set(""))

        self.results = ScrollArea(panel, PANEL_BG)
        self.results.pack(fill="both", expand=True, padx=8, pady=12)
        self.update_results()

    def update_results(self):
        self.results.clear()
        words = self.query.get().lower().split()
        if not words:
            tk.Label(self.results.inner, text="Type to search your ideas.", bg=PANEL_BG, fg=DIM_TEXT,
                     font=(FONT, 10), anchor="w", padx=10).pack(fill="x")
            return
        found = 0
        for idea in reversed(self.chronological()):            # newest first
            title, text = title_and_text(idea)
            notes = " ".join(n["text"] for n in self.store.notes_of(idea))
            haystack = (title + " " + text + " " + notes).lower()
            if all(word in haystack for word in words):        # every word must appear
                self.add_result(idea, title, text + " " + notes, words[0])
                found += 1
        if not found:
            tk.Label(self.results.inner, text="No ideas match.", bg=PANEL_BG, fg=DIM_TEXT,
                     font=(FONT, 10), anchor="w", padx=10).pack(fill="x")

    def add_result(self, idea, title, text, word):
        name = idea["created"]
        row = make_row(self.results.inner, PANEL_BG, lambda: self.go_to(name))
        row.pack(fill="x", pady=1)
        text = text.strip()
        tk.Label(row, text=title or "(no title)", bg=PANEL_BG, fg=TEXT, font=(FONT, 10),
                 anchor="w", padx=10, pady=(6 if text else 7), wraplength=PANEL_WIDTH - 50,
                 justify="left").pack(fill="x")
        if text:
            # A short piece of the text around the first matching word.
            flat = text.replace("\n", " ")
            at = max(0, flat.lower().find(word) - 30)
            snippet = ("…" if at else "") + flat[at:at + 90] + ("…" if len(flat) > at + 90 else "")
            tk.Label(row, text=snippet, bg=PANEL_BG, fg=DIM_TEXT, font=(FONT, 9), anchor="w",
                     padx=10, wraplength=PANEL_WIDTH - 50, justify="left").pack(fill="x", pady=(0, 6))
        bind_children(row)

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

        # --- The galaxy ---
        self.canvas = tk.Canvas(middle, bg=g3d.SPACE_HEX, highlightthickness=0, borderwidth=0,
                                takefocus=1)
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<Configure>", lambda e: self.request_sharp())
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
        self.image_item = None
        self.photo = None

    def update_topbar(self):
        links = len(self.store.links)
        self.stats_label.config(text=f"{len(self.ideas)} ideas   ·   {links} link{'s' if links != 1 else ''}")
        if self.linking:
            title = title_and_text(self.idea(self.linking) or {"text": ""})[0]
            self.hint_label.config(text=f"Click a star or an idea to link it with “{title[:30]}”   ·   Esc to cancel")
        else:
            self.hint_label.config(text="")

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
        Turn the ideas into a galaxy scene. With the timeline on, only the
        ideas up to the slider's date are included.
        """
        ideas = self.chronological()
        if self.timeline is not None:
            ideas = ideas[:self.timeline]
        self.shown = [i["created"] for i in ideas]          # scene number -> name tag
        self.scene_number = {name: n for n, name in enumerate(self.shown)}
        self.scene = g3d.Scene([i["slot"] for i in ideas], [colour_index(i) for i in ideas],
                               [len(self.store.notes_of(i)) for i in ideas],
                               [glow_from_activity(self.store.activity(i)) for i in ideas])
        self.hovered = None

    def refresh_brightness(self):
        """Update only how bright each star is (cheaper than rebuilding the scene)."""
        brightness = []
        for name in self.shown:
            idea = self.idea(name)
            brightness.append(glow_from_activity(self.store.activity(idea)) if idea else 0.45)
        self.scene.brightness = brightness
        self.request_sharp()

    def view_size(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

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
        """
        Draw the galaxy. While things move (`moving=True`) only the soft gas is
        drawn at lower resolution; stars are always sharp (see galaxy3d.render).
        """
        w, h = self.view_size()
        if w < 10 or h < 10:
            return
        if not self.fitted:
            self.fit_camera()
        picture, self.screen, self.visible = g3d.render(self.scene, self.camera, w, h, moving=moving)
        self.photo = ImageTk.PhotoImage(picture)   # keep a reference, or Tkinter forgets it
        if self.image_item is None:
            self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        else:
            self.canvas.itemconfigure(self.image_item, image=self.photo)
        self.draw_marks()

    def request_sharp(self):
        """Draw one sharp picture soon (unless the animation is running: it will)."""
        if self.anim is None:
            if self.sharp_pending:
                self.root.after_cancel(self.sharp_pending)
            self.sharp_pending = self.root.after(30, self.sharp_now)

    def sharp_now(self):
        self.sharp_pending = None
        if self.anim is None:
            self.render(moving=False)

    def draw_marks(self):
        """Constellation lines, the ring around the selected star, the hover label."""
        c = self.canvas
        c.delete("mark")
        if not self.scene.count or not len(self.screen):
            return
        w, h = self.view_size()
        # Constellation lines: a faint line between every pair of linked stars.
        _, _, depth, _ = self.camera.project(self.scene.ideas, w, h)
        for link in self.store.links:
            a, b = (self.scene_number.get(x) for x in link["link"])
            if a is None or b is None or depth[a] < 0.01 or depth[b] < 0.01:
                continue
            lit = self.selected in link["link"]
            (x1, y1), (x2, y2) = self.screen[a], self.screen[b]
            # Stop the line a few pixels before each star, so it doesn't cover it.
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 12:
                continue
            ux, uy = dx / length, dy / length
            c.create_line(x1 + ux * 6, y1 + uy * 6, x2 - ux * 6, y2 - uy * 6,
                          fill=LINK_LINE_LIT if lit else LINK_LINE, width=1, tags="mark")
        n = self.scene_number.get(self.selected)
        if n is not None and self.visible[n]:
            x, y = self.screen[n]
            c.create_oval(x - 11, y - 11, x + 11, y + 11, outline="#8f8d86", width=1, tags="mark")
        n = self.hovered
        if n is not None and n < len(self.visible) and self.visible[n]:
            title = title_and_text(self.idea(self.shown[n]))[0]
            if len(title) > 50:
                title = title[:49] + "…"
            x, y = self.screen[n]
            label = c.create_text(x + 16, y - 12, text=title or "(no title)", anchor="sw",
                                  fill=TEXT, font=(FONT, 10), tags="mark")
            x1, y1, x2, y2 = c.bbox(label)
            box = rounded_rectangle(c, x1 - 9, y1 - 5, x2 + 9, y2 + 5, 8,
                                    fill="#16161a", outline="#33343a", tags="mark")
            c.tag_lower(box, label)

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
            self.canvas.config(cursor="hand2" if n is not None or self.linking else "")
            self.draw_marks()

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
        self.glide = 4.0                           # slower: a calm flight
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
