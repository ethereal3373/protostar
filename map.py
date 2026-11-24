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
    """Read ideas.jsonl and return a list of ideas (oldest first)."""
    if not path.exists():
        return []
    ideas = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:  # skip empty lines
                ideas.append(json.loads(line))  # turn one line of JSON into a dict
    return ideas


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
        self.ideas = load_ideas(path)
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

        self.scene = g3d.Scene(len(self.ideas), lambda n: colour_index(self.ideas[n]))
        self.camera = g3d.Camera()
        self.fitted = False
        self.render_pending = None
        self.sharp_pending = None
        self.dragged = False
        self.flight = None
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
        shown = title if len(title) <= 30 else title[:29] + "…"
        tk.Label(row, text=shown or "(no title)", bg=bg, fg=TEXT if selected else SOFT_TEXT,
                 font=(FONT, 10), anchor="w", pady=5).pack(side="left", fill="x", expand=True)
        bind_children(row)
        if is_open:
            # The opened idea: date and full text, indented under its title.
            when = datetime.fromisoformat(idea["created"]).strftime("%d %b %Y, %H:%M")
            body = tk.Frame(box, bg=SIDEBAR_BG)
            body.pack(fill="x", padx=(44, 10), pady=(0, 8))
            tk.Label(body, text=when, bg=SIDEBAR_BG, fg=DIM_TEXT, font=(FONT, 8),
                     anchor="w").pack(fill="x")
            if text:
                tk.Label(body, text=text, bg=SIDEBAR_BG, fg=SOFT_TEXT, font=(FONT, 10),
                         wraplength=SIDEBAR_WIDTH - 70, justify="left", anchor="w").pack(fill="x", pady=(2, 0))
        self.idea_rows[i] = box

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
        self.request_render()

    def reveal_in_sidebar(self, i):
        """Select idea i, open it (and its month folder), and scroll to it."""
        self.selected = i
        self.open_ideas.add(i)
        self.closed_months.discard(self.ideas[i]["created"][:7])
        self.fill_sidebar()
        if i in self.idea_rows:
            self.tree.scroll_to(self.idea_rows[i])
        self.request_render()

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
            haystack = (title + " " + text).lower()
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
        self.canvas = tk.Canvas(self.root, bg=g3d.SPACE_HEX, highlightthickness=0, borderwidth=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.request_render(moving=False))
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_orbit)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", self.on_press)
        self.canvas.bind("<B3-Motion>", self.on_pan)
        self.canvas.bind("<ButtonRelease-3>", lambda e: setattr(self, "dragged", False))
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self.set_hover(None))
        self.image_item = None
        self.photo = None

    def view_size(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def fit_camera(self):
        """Start with all ideas in view, seen from above at an angle."""
        if len(self.ideas):
            pts = self.scene.ideas
            centre = pts.mean(axis=0)
            spread = float(np.max(np.linalg.norm(pts - centre, axis=1)))
            self.camera.target = centre.astype(np.float32)
            self.camera.dist = 2.4 * max(0.12, spread * 1.2)
        else:
            self.camera.dist = 2.0
        self.fitted = True

    def request_render(self, moving=True):
        """
        Ask for a new picture. If one is already coming, do nothing: while you
        drag, many mouse events arrive between two pictures, and we only need
        to draw the latest view (this keeps the CPU from drowning).
        """
        if self.render_pending is None:
            self.render_pending = self.root.after(12, lambda: self.render(moving))

    def render(self, moving=False):
        """
        Draw the galaxy. While things move (`moving=True`) we draw a smaller
        picture and stretch it — about 2.5x less work, so turning feels
        smoother — and 150 ms after the movement stops, one sharp picture.
        """
        self.render_pending = None
        w, h = self.view_size()
        if w < 10 or h < 10:
            return
        if not self.fitted:
            self.fit_camera()
        scale = 0.62 if moving else 1.0
        rw, rh = max(10, int(w * scale)), max(10, int(h * scale))
        picture, screen, self.visible = g3d.render(self.scene, self.camera, rw, rh)
        self.screen = screen / scale
        if moving:
            picture = picture.resize((w, h), Image.BILINEAR)
            if self.sharp_pending:
                self.root.after_cancel(self.sharp_pending)
            self.sharp_pending = self.root.after(150, self.sharp_render)
        self.photo = ImageTk.PhotoImage(picture)   # keep a reference, or Tkinter forgets it
        if self.image_item is None:
            self.image_item = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        else:
            self.canvas.itemconfigure(self.image_item, image=self.photo)
        self.draw_marks()

    def sharp_render(self):
        self.sharp_pending = None
        if self.flight is None and not self.dragged:
            self.render(moving=False)
        else:
            self.sharp_pending = self.root.after(150, self.sharp_render)

    def draw_marks(self):
        """The ring around the selected star and the hover label (drawn over the picture)."""
        self.canvas.delete("mark")
        if self.selected is not None and self.selected < len(self.visible) and self.visible[self.selected]:
            x, y = self.screen[self.selected]
            self.canvas.create_oval(x - 13, y - 13, x + 13, y + 13, outline="#9a988f",
                                    width=1, tags="mark")
        if self.hovered is not None and self.hovered < len(self.visible) and self.visible[self.hovered]:
            title, _ = title_and_text(self.ideas[self.hovered])
            if len(title) > 50:
                title = title[:49] + "…"
            x, y = self.screen[self.hovered]
            label = self.canvas.create_text(x + 18, y - 14, text=title or "(no title)", anchor="sw",
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

    # --- Mouse ---
    def on_motion(self, event):
        self.set_hover(self.star_at(event.x, event.y))

    def on_press(self, event):
        self.last = (event.x, event.y)
        self.press = (event.x, event.y)
        self.dragged = False
        self.flight = None          # grabbing the view stops any camera flight

    def drag_amount(self, event):
        dx, dy = event.x - self.last[0], event.y - self.last[1]
        self.last = (event.x, event.y)
        if abs(event.x - self.press[0]) + abs(event.y - self.press[1]) > 3:
            self.dragged = True
        return dx, dy

    def on_orbit(self, event):
        """Left drag: walk around the galaxy (yaw) and move up/down over it (pitch)."""
        dx, dy = self.drag_amount(event)
        if not self.dragged:
            return
        self.camera.yaw -= dx * 0.006
        limit = math.radians(89)
        self.camera.pitch = min(limit, max(-limit, self.camera.pitch + dy * 0.006))
        self.set_hover(None)
        self.request_render()

    def on_pan(self, event):
        """Right drag: slide the view sideways / up and down."""
        dx, dy = self.drag_amount(event)
        _, right, up, _ = self.camera.basis()
        w, h = self.view_size()
        per_pixel = self.camera.dist / (0.8 * min(w, h))
        self.camera.target = (self.camera.target - right * dx * per_pixel
                              + up * dy * per_pixel).astype(np.float32)
        self.set_hover(None)
        self.request_render()

    def on_release(self, event):
        if not self.dragged:
            n = self.star_at(event.x, event.y)
            if n is not None:
                self.reveal_in_sidebar(n)
            else:
                self.selected = None
                self.draw_marks()
        self.dragged = False

    def on_wheel(self, event):
        """Zoom: move the camera closer or further."""
        factor = 0.85 if event.delta > 0 else 1 / 0.85
        self.camera.dist = min(8.0, max(0.03, self.camera.dist * factor))
        self.flight = None
        self.request_render()

    # --- Flying the camera to a star ---
    def fly_to(self, n, frames=28):
        """Glide the camera so that idea n is in the middle, a bit closer."""
        if n >= len(self.ideas):
            return
        start_target = self.camera.target.copy()
        end_target = self.scene.ideas[n].copy()
        start_dist = self.camera.dist
        end_dist = min(start_dist, 0.35)
        self.flight = (n, 0, frames, start_target, end_target, start_dist, end_dist)
        self.fly_step()

    def fly_step(self):
        if self.flight is None:
            return
        n, i, frames, t0, t1, d0, d1 = self.flight
        i += 1
        t = i / frames
        ease = t * t * (3 - 2 * t)      # "smoothstep": starts and ends gently
        self.camera.target = (t0 + (t1 - t0) * ease).astype(np.float32)
        self.camera.dist = d0 + (d1 - d0) * ease
        self.render(moving=True)
        if i < frames:
            self.flight = (n, i, frames, t0, t1, d0, d1)
            self.root.after(16, self.fly_step)
        else:
            self.flight = None

    # ------------------------------------------------------------------
    # New ideas
    # ------------------------------------------------------------------
    def check_for_new_ideas(self):
        """
        Runs once a second. If ideas.jsonl changed (you saved an idea with
        Ctrl+Alt+I), reload, rebuild the galaxy and fly to the new star.
        """
        stamp = file_stamp(self.path)
        if stamp != self.stamp:
            self.stamp = stamp
            old = len(self.ideas)
            self.ideas = load_ideas(self.path)
            self.scene = g3d.Scene(len(self.ideas), lambda n: colour_index(self.ideas[n]))
            if self.selected is not None and self.selected >= len(self.ideas):
                self.selected = None
            self.update_results()
            if len(self.ideas) > old:
                newest = len(self.ideas) - 1
                self.reveal_in_sidebar(newest)
                self.fly_to(newest)
            else:
                self.fill_sidebar()
                self.request_render()
        self.root.after(CHECK_EVERY_MS, self.check_for_new_ideas)


def main():
    # If a file was given after "python map.py", use it; otherwise use the real ideas.
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IDEAS_FILE
    ProtostarApp(path).root.mainloop()


if __name__ == "__main__":
    main()
