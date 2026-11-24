"""
map.py — the main Protostar app: your ideas as a 3D galaxy.

Run it with:   python map.py      (or press Ctrl+Alt+M while Protostar runs)
(For testing you can give it another ideas file:  python map.py some_file.jsonl)

Layout
------
  Left:   sidebar with all your ideas, in folders by month. Click a folder
          to open/close it; click an idea to open/close it and fly to its star.
  Middle: the galaxy.
            drag (left button)   -> turn around the galaxy
            drag (right button)  -> slide sideways
            mouse wheel          -> zoom in/out
            hover a star         -> its title
            click a star         -> open that idea in the sidebar
  Right:  search through all your ideas (titles and text).

This is a SEPARATE program from protostar.py: it only runs while it's
open, so it adds nothing to the always-running part. And it only uses
CPU while something moves: when you don't touch it, it sleeps.
"""

import ctypes
import json
import math
import sys
import time
import tkinter as tk
import zlib
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageTk  # ImageTk turns Pillow pictures into Tkinter ones

import galaxy3d as g3d
# Reuse the same file location and window title as the always-running part.
from protostar import IDEAS_FILE, MAP_TITLE

# --- Colours: dark, warm greys (similar to the Claude app) ---
SIDEBAR_BG = "#1f1e1d"
PANEL_BG = "#1f1e1d"
EDGE = "#2f2e2b"           # thin lines between areas
ROW_HOVER = "#2a2927"
ROW_SELECTED = "#34332f"
INPUT_BG = "#2a2927"
TEXT = "#eeede9"
SOFT_TEXT = "#bdbbb3"
DIM_TEXT = "#83817a"
ACCENT = "#d97757"         # a warm clay orange, used very sparingly
FONT = "Segoe UI"

SIDEBAR_WIDTH = 280
PANEL_WIDTH = 300
CHECK_EVERY_MS = 1000      # how often to look for new ideas


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def load_ideas(path):
    """
    Read ideas.jsonl. Returns (ideas, notes):
      ideas = list of main ideas, oldest first
      notes = {an idea's "created" time: [its notes, oldest first]}
    A note is a line with a "parent" field: the "created" time of its idea.
    (That time works as the idea's name tag: no two ideas share the same second.)
    """
    ideas, notes = [], {}
    if not path.exists():
        return ideas, notes
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:  # skip empty lines
                continue
            record = json.loads(line)  # turn one line of JSON into a dict
            if "parent" in record:
                notes.setdefault(record["parent"], []).append(record)
            else:
                ideas.append(record)
    return ideas, notes


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
    """A cheap "fingerprint" of the file (time changed + size), to notice new ideas."""
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
    row.paint = paint
    return row


def bind_children(row):
    """Make clicks/hover on a row's labels behave like clicks/hover on the row."""
    for child in row.winfo_children():
        for event in ("<Button-1>", "<Enter>", "<Leave>"):
            child.bind(event, lambda e, ev=event: row.event_generate(ev, x=0, y=0))


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------

class ProtostarApp:
    def __init__(self, path):
        self.path = path
        self.ideas, self.notes = load_ideas(path)
        self.stamp = file_stamp(path)

        self.root = tk.Tk()
        self.root.title(MAP_TITLE)
        self.root.configure(bg=SIDEBAR_BG)
        w, h = 1400, 860
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(900, 560)
        dark_title_bar(self.root)

        self.selected = None          # number of the selected idea
        self.open_ideas = set()       # ideas opened in the sidebar (showing their text)
        self.closed_months = set()    # month folders the user closed
        self.hovered = None

        self.build_sidebar()
        self.build_search_panel()
        self.build_galaxy_view()

        self.build_scene()
        # Two cameras: `camera` is what we draw; `goal` is where your mouse and
        # keys say it should be. Each frame, `camera` glides part of the way
        # towards `goal`: that's what makes movement feel smooth.
        self.camera = g3d.Camera()
        self.goal = g3d.Camera()
        self.pivot = np.zeros(3)      # the point that left-drag circles around
        self.glide = 12.0             # how quickly the camera catches up (bigger = faster)
        self.fitted = False
        self.keys = set()             # movement keys being held (W, A, S, D, Q, E)
        self.anim = None              # the running animation loop, if any
        self.last_tick = 0.0
        self.sharp_pending = None
        self.dragged = False
        self.mode = "orbit"
        self.screen = np.zeros((0, 2))
        self.visible = np.zeros(0, bool)

        self.fill_sidebar()
        self.root.after(CHECK_EVERY_MS, self.check_for_new_ideas)

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

        # "New idea" button: presses Ctrl+Alt+I for you, which opens the capture
        # note (if Protostar is running in the background).
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
        n = len(self.ideas)
        self.count_label.config(text=f"IDEAS  ·  {n}")
        if not n:
            tk.Label(self.tree.inner, text="No ideas yet.\nPress Ctrl+Alt+I to catch one.",
                     bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 10), justify="left",
                     anchor="w", padx=10, pady=8).pack(fill="x")
            return

        # Group ideas by month, newest month first, newest idea first.
        months = {}
        for i, idea in enumerate(self.ideas):
            months.setdefault(idea["created"][:7], []).append(i)   # "2026-11"
        for month in sorted(months, reverse=True):
            numbers = list(reversed(months[month]))
            is_open = month not in self.closed_months
            name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")

            folder = make_row(self.tree.inner, SIDEBAR_BG, lambda m=month: self.toggle_month(m))
            folder.pack(fill="x", pady=(4, 0))
            tk.Label(folder, text="▾" if is_open else "▸", bg=SIDEBAR_BG, fg=DIM_TEXT,
                     font=(FONT, 9), width=2).pack(side="left", padx=(6, 0))
            tk.Label(folder, text=name, bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT + " Semibold", 10),
                     anchor="w", pady=6).pack(side="left")
            tk.Label(folder, text=str(len(numbers)), bg=SIDEBAR_BG, fg=DIM_TEXT,
                     font=(FONT, 9), padx=10).pack(side="right")
            bind_children(folder)
            if not is_open:
                continue
            for i in numbers:
                self.add_idea_row(i)

    def add_idea_row(self, i):
        idea = self.ideas[i]
        title, text = title_and_text(idea)
        selected = i == self.selected
        bg = ROW_SELECTED if selected else SIDEBAR_BG
        box = tk.Frame(self.tree.inner, bg=SIDEBAR_BG)
        box.pack(fill="x")
        row = make_row(box, bg, lambda: self.toggle_idea(i))
        row.pack(fill="x", padx=(18, 0))
        is_open = i in self.open_ideas
        tk.Label(row, text="▾" if is_open else "▸", bg=bg, fg=DIM_TEXT, font=(FONT, 8),
                 width=2).pack(side="left", padx=(4, 0))
        notes = self.notes.get(idea["created"], [])
        if notes:   # how many notes this idea has, in small grey numbers on the right
            tk.Label(row, text=str(len(notes)), bg=bg, fg=DIM_TEXT, font=(FONT, 8),
                     padx=8).pack(side="right")
        shown = title if len(title) <= 28 else title[:27] + "…"
        tk.Label(row, text=shown or "(no title)", bg=bg, fg=TEXT if selected else SOFT_TEXT,
                 font=(FONT, 10), anchor="w", pady=5).pack(side="left", fill="x", expand=True)
        bind_children(row)
        if is_open:
            # The opened idea: date, full text, its notes, and a box to add a note.
            when = datetime.fromisoformat(idea["created"]).strftime("%d %b %Y, %H:%M")
            body = tk.Frame(box, bg=SIDEBAR_BG)
            body.pack(fill="x", padx=(44, 10), pady=(0, 8))
            tk.Label(body, text=when, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8),
                     anchor="w").pack(fill="x")
            if text:
                tk.Label(body, text=text, bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT, 10),
                         wraplength=SIDEBAR_WIDTH - 70, justify="left", anchor="w").pack(fill="x", pady=(2, 0))
            for note in notes:
                line = tk.Frame(body, bg=SIDEBAR_BG)
                line.pack(fill="x", pady=(6, 0))
                tk.Label(line, text="·", bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 10)).pack(side="left", anchor="n")
                tk.Label(line, text=note["text"], bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT, 9),
                         wraplength=SIDEBAR_WIDTH - 85, justify="left", anchor="w").pack(side="left", fill="x", padx=(4, 0))
            self.add_note_box(body, idea)
        self.idea_rows[i] = box

    def add_note_box(self, parent, idea):
        """A small text field under an open idea: type a note and press Enter."""
        hint = "Add a note…"
        entry = tk.Entry(parent, bg=SIDEBAR_BG, fg=DIM_TEXT, insertbackground=TEXT, relief="flat",
                         font=(FONT, 9), highlightthickness=1, highlightbackground=EDGE,
                         highlightcolor="#4a4945", borderwidth=4)
        entry.insert(0, hint)
        entry.pack(fill="x", pady=(8, 0))

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
                self.save_note(idea, text)

        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)
        entry.bind("<Return>", save)
        entry.bind("<Escape>", lambda e: self.canvas.focus_set())

    def toggle_month(self, month):
        self.closed_months ^= {month}   # ^= flips: add it if missing, remove it if present
        self.fill_sidebar()

    def toggle_idea(self, i):
        """Click on an idea in the sidebar: open/close it, select it, fly to its star."""
        if i in self.open_ideas and self.selected == i:
            self.open_ideas.discard(i)
        else:
            self.open_ideas.add(i)
            self.fly_to(i)
        self.selected = i
        self.fill_sidebar()
        self.draw_marks()

    def reveal_in_sidebar(self, i):
        """Select idea i, open it (and its month folder), and scroll to it."""
        self.selected = i
        self.open_ideas.add(i)
        self.closed_months.discard(self.ideas[i]["created"][:7])
        self.fill_sidebar()
        if i in self.idea_rows:
            self.tree.scroll_to(self.idea_rows[i])
        self.draw_marks()

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
        for i in reversed(range(len(self.ideas))):            # newest first
            title, text = title_and_text(self.ideas[i])
            notes = " ".join(note["text"] for note in self.notes.get(self.ideas[i]["created"], []))
            haystack = (title + " " + text + " " + notes).lower()
            if all(word in haystack for word in words):        # every word must appear
                self.add_result(i, title, text, words[0])
                found += 1
        if not found:
            tk.Label(self.results.inner, text="No ideas match.", bg=PANEL_BG, fg=DIM_TEXT,
                     font=(FONT, 10), anchor="w", padx=10).pack(fill="x")

    def add_result(self, i, title, text, word):
        row = make_row(self.results.inner, PANEL_BG, lambda: (self.reveal_in_sidebar(i), self.fly_to(i)))
        row.pack(fill="x", pady=1)
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
    # Middle: the galaxy
    # ------------------------------------------------------------------
    def build_galaxy_view(self):
        self.canvas = tk.Canvas(self.root, bg=g3d.SPACE_HEX, highlightthickness=0, borderwidth=0,
                                takefocus=1)
        self.canvas.pack(side="left", fill="both", expand=True)
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
        self.image_item = None
        self.photo = None

    def view_size(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def fit_camera(self):
        """A view of all the ideas, from above at an angle."""
        if len(self.ideas):
            pts = self.scene.ideas.astype(np.float64)
            centre = pts.mean(axis=0)
            spread = float(np.max(np.linalg.norm(pts - centre, axis=1)))
        else:
            centre, spread = np.zeros(3), 0.6
        self.pivot = centre
        self.goal = g3d.Camera(yaw=0.0, pitch=-0.8)
        self.goal.look_at(centre, 1.6 * max(0.10, spread))
        self.camera = self.goal.copy()
        self.fitted = True

    # --- Drawing ---
    def render(self, moving=False):
        """
        Draw the galaxy. While things move (`moving=True`) we draw a picture
        half the size and stretch it (4x fewer pixels to work on, so motion
        stays smooth); when everything stops, one sharp picture.
        """
        w, h = self.view_size()
        if w < 10 or h < 10:
            return
        if not self.fitted:
            self.fit_camera()
        scale = 0.5 if moving else 1.0
        rw, rh = max(10, int(w * scale)), max(10, int(h * scale))
        picture, screen, self.visible = g3d.render(self.scene, self.camera, rw, rh)
        self.screen = screen / scale
        if moving:
            picture = picture.resize((w, h), Image.BILINEAR)
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
        """The ring around the selected star and the hover label (drawn over the picture)."""
        self.canvas.delete("mark")
        if self.selected is not None and self.selected < len(self.visible) and self.visible[self.selected]:
            x, y = self.screen[self.selected]
            self.canvas.create_oval(x - 11, y - 11, x + 11, y + 11, outline="#8f8d86",
                                    width=1, tags="mark")
        if self.hovered is not None and self.hovered < len(self.visible) and self.visible[self.hovered]:
            title, _ = title_and_text(self.ideas[self.hovered])
            if len(title) > 50:
                title = title[:49] + "…"
            x, y = self.screen[self.hovered]
            label = self.canvas.create_text(x + 16, y - 12, text=title or "(no title)", anchor="sw",
                                            fill=TEXT, font=(FONT, 10), tags="mark")
            x1, y1, x2, y2 = self.canvas.bbox(label)
            box = rounded_rectangle(self.canvas, x1 - 9, y1 - 5, x2 + 9, y2 + 5, 8,
                                    fill="#16161a", outline="#33343a", tags="mark")
            self.canvas.tag_lower(box, label)

    def star_at(self, x, y):
        """The idea whose star is closest to (x, y), if it's within 12 pixels."""
        if not len(self.screen):
            return None
        d = np.hypot(self.screen[:, 0] - x, self.screen[:, 1] - y)
        d[~self.visible] = np.inf
        n = int(np.argmin(d))
        return n if d[n] <= 12 else None

    def set_hover(self, n):
        if n != self.hovered:
            self.hovered = n
            self.canvas.config(cursor="hand2" if n is not None else "")
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
            self.anim = self.root.after(12, self.tick)
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
            if n is not None:
                self.reveal_in_sidebar(n)
            else:
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
        elif key == "shift_l" or key == "shift_r":
            self.keys.add("shift")
        elif key == "f" and self.selected is not None:
            self.fly_to(self.selected)                 # F = focus on the selected star
        elif key == "home":
            self.fit_camera()
            self.render()

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
    def fly_to(self, n):
        """Glide the camera towards idea n, keeping the same viewing angle."""
        if n >= len(self.ideas):
            return
        star = self.scene.ideas[n].astype(np.float64)
        distance = min(0.12, float(np.linalg.norm(star - self.goal.position)))
        self.goal.look_at(star, max(0.03, distance))
        self.pivot = star
        self.glide = 4.0                           # slower: a calm flight
        self.start_animation()

    # ------------------------------------------------------------------
    # New ideas and notes
    # ------------------------------------------------------------------
    def build_scene(self):
        counts = [len(self.notes.get(idea["created"], [])) for idea in self.ideas]
        self.scene = g3d.Scene(len(self.ideas), lambda n: colour_index(self.ideas[n]), counts)

    def reload(self):
        """Read the file again and refresh everything. Returns how many ideas were added."""
        self.stamp = file_stamp(self.path)
        old = len(self.ideas)
        self.ideas, self.notes = load_ideas(self.path)
        self.build_scene()
        if self.selected is not None and self.selected >= len(self.ideas):
            self.selected = None
        self.update_results()
        return len(self.ideas) - old

    def check_for_new_ideas(self):
        """
        Runs once a second. If ideas.jsonl changed (you saved an idea with
        Ctrl+Alt+I), reload, rebuild the galaxy and fly to the new star.
        """
        if file_stamp(self.path) != self.stamp:
            if self.reload() > 0:
                newest = len(self.ideas) - 1
                self.reveal_in_sidebar(newest)
                self.fly_to(newest)
            else:
                self.fill_sidebar()
                self.request_sharp()
        self.root.after(CHECK_EVERY_MS, self.check_for_new_ideas)

    def save_note(self, idea, text):
        """Add a note under `idea` (a new line in ideas.jsonl that points to its parent)."""
        note = {"created": datetime.now().isoformat(timespec="seconds"),
                "parent": idea["created"], "text": text}
        self.path.parent.mkdir(exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(note, ensure_ascii=False) + "\n")
        self.reload()
        self.fill_sidebar()
        self.request_sharp()

def main():
    # If a file was given after "python map.py", use it; otherwise use the real ideas.
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IDEAS_FILE
    ProtostarApp(path).root.mainloop()


if __name__ == "__main__":
    main()
