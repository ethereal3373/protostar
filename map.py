"""
map.py — the galaxy map: every saved idea is a star in a spiral galaxy.

Run it with:   python map.py      (or press Ctrl+Alt+M while Protostar runs)
(For testing you can give it another ideas file:  python map.py some_file.jsonl)

  - Scroll the mouse wheel to zoom in and out (towards the mouse pointer).
  - Drag with the left mouse button to move around.
  - Hover a star to see its title; click it to read the whole idea.
  - Esc closes the idea card, or the map if no card is open.

This is a SEPARATE program from protostar.py. It only runs while you look
at it, so it adds nothing to the always-running part.

The big idea: "world" and "screen" coordinates
----------------------------------------------
The galaxy picture is big (3072 x 2048 pixels) — the "world". The window
only shows part of it, at some zoom level — the "screen". Two numbers
connect them:
    screen = world * zoom + offset
Zooming changes `zoom`, dragging changes `offset`. Every star is stored
in world coordinates and converted to the screen each time we draw.
"""

import json
import sys
import tkinter as tk
import zlib
from pathlib import Path

from PIL import Image, ImageTk  # ImageTk turns Pillow pictures into Tkinter ones

import galaxy_art as art
# Reuse the same file location and window title as the always-running part.
from protostar import IDEAS_FILE, MAP_TITLE

# --- Look and feel: neutral greys, nothing purple ---
TEXT = "#ececec"
SOFT_TEXT = "#a9adb3"
DIM_TEXT = "#5f646b"
CARD_BG = "#0c0e12"
CARD_EDGE = "#2a2e35"
FONT = "Segoe UI"

MAX_ZOOM = 3.0           # 3 screen pixels per galaxy pixel at most
MARGIN = 0.5             # draw the background half a window beyond each edge
CHECK_EVERY_MS = 1000    # how often to look for new ideas


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
    Return (title, text) for an idea.
    New ideas store them separately. Ideas saved before titles existed
    only have "text", so we use their first line as the title.
    """
    if "title" in idea:
        return idea["title"], idea["text"]
    title, _, text = idea["text"].partition("\n")
    return title, text


def file_stamp(path):
    """
    A quick "fingerprint" of the file: when it was last changed and its size.
    If the fingerprint changes, someone saved a new idea. Checking it is
    very cheap: Windows already knows these two numbers, the file isn't read.
    """
    try:
        info = path.stat()
        return (info.st_mtime_ns, info.st_size)
    except FileNotFoundError:
        return None


def rounded_rectangle(canvas, x1, y1, x2, y2, radius, **options):
    """
    Tkinter has no rounded rectangles, so we draw a polygon with smooth=True:
    Tkinter then bends the lines into curves. Doubling the corner points
    keeps the straight edges straight.
    """
    r = radius
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, x1, y1]
    return canvas.create_polygon(points, smooth=True, **options)


def dark_title_bar(window):
    """Ask Windows to draw this window's title bar dark (Windows 10/11)."""
    import ctypes
    window.update_idletasks()
    hwnd = int(window.wm_frame(), 16)
    on = ctypes.c_int(1)
    ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))


class GalaxyMap:
    def __init__(self, path):
        self.path = path
        self.ideas = load_ideas(path)
        self.stamp = file_stamp(path)

        self.root = tk.Tk()
        # The title never changes: protostar.py uses it to find this window.
        self.root.title(MAP_TITLE)
        self.root.configure(bg=art.SPACE_HEX)
        w, h = 1200, 800
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        dark_title_bar(self.root)

        self.canvas = tk.Canvas(self.root, bg=art.SPACE_HEX, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # The first time ever, painting the galaxy takes a few seconds:
        # show a message so the window isn't just black.
        if not art.CACHE_FILE.exists():
            self.canvas.create_text(w / 2, h / 2, text="Painting your galaxy for the first time…",
                                    fill=SOFT_TEXT, font=(FONT, 12))
            self.root.update()
        self.galaxy = art.load_galaxy()

        # View: screen = world * zoom + offset
        self.zoom = None          # decided on the first draw, once we know the window size
        self.offset = (0.0, 0.0)

        self.background = None    # the Tkinter picture currently on screen (must be kept!)
        self.sprites = {}         # star pictures, made once and reused
        self.star_items = {}      # canvas item id -> idea number
        self.selected = None      # idea number whose card is open
        self.hovered = None
        self.drag_start = None
        self.redraw_pending = None

        # --- Mouse and keyboard ---
        self.canvas.bind("<Configure>", lambda e: self.schedule_redraw())
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_motion)
        self.root.bind("<Escape>", self.on_escape)

        # Draw once now: the window may already have its size, in which case
        # no <Configure> event would come to trigger the first drawing.
        self.schedule_redraw()
        self.root.after(CHECK_EVERY_MS, self.check_for_new_ideas)

    # ------------------------------------------------------------------
    # World <-> screen
    # ------------------------------------------------------------------
    def to_screen(self, wx, wy):
        return wx * self.zoom + self.offset[0], wy * self.zoom + self.offset[1]

    def to_world(self, sx, sy):
        return (sx - self.offset[0]) / self.zoom, (sy - self.offset[1]) / self.zoom

    def size(self):
        return self.canvas.winfo_width(), self.canvas.winfo_height()

    def min_zoom(self):
        """The smallest zoom where the galaxy picture still covers the whole window."""
        w, h = self.size()
        return max(w / art.SRC_W, h / art.SRC_H)

    def keep_in_bounds(self):
        """Don't let the view slide past the edges of the galaxy picture."""
        w, h = self.size()
        self.zoom = min(MAX_ZOOM, max(self.min_zoom(), self.zoom))
        ox = min(0, max(w - art.SRC_W * self.zoom, self.offset[0]))
        oy = min(0, max(h - art.SRC_H * self.zoom, self.offset[1]))
        self.offset = (ox, oy)

    def fit_view(self):
        """First view: zoom so that all ideas (and some galaxy around them) fit."""
        w, h = self.size()
        points = [art.idea_position(n) for n in range(len(self.ideas))]
        # Always include a decent part of the galaxy, so a few ideas near
        # the core don't make us zoom in absurdly far.
        r = art.GALAXY_R * 0.55
        points += [(art.CENTER_X - r, art.CENTER_Y - r), (art.CENTER_X + r, art.CENTER_Y + r)]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
        self.zoom = 0.85 * min(w / span_x, h / span_y)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.offset = (w / 2 - cx * self.zoom, h / 2 - cy * self.zoom)
        self.keep_in_bounds()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def schedule_redraw(self):
        """
        Resizing the window fires many <Configure> events in a row. Instead of
        redrawing for each one, wait until they stop for 60 ms ("debouncing").
        """
        if self.redraw_pending:
            self.root.after_cancel(self.redraw_pending)
        self.redraw_pending = self.root.after(60, self.redraw)

    def redraw(self):
        self.redraw_pending = None
        if self.zoom is None:
            self.fit_view()
        self.keep_in_bounds()
        self.draw_background()
        self.draw_stars()
        self.draw_overlay()

    def draw_background(self):
        """
        Cut out the part of the galaxy picture we can see (plus a margin, so
        dragging doesn't immediately reveal black edges), scale it to the
        current zoom, and put it on the canvas.
        """
        w, h = self.size()
        mx, my = w * MARGIN, h * MARGIN
        x0, y0 = self.to_world(-mx, -my)
        x1, y1 = self.to_world(w + mx, h + my)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(art.SRC_W, int(x1) + 1), min(art.SRC_H, int(y1) + 1)
        piece = self.galaxy.crop((x0, y0, x1, y1))
        out_w = max(1, round((x1 - x0) * self.zoom))
        out_h = max(1, round((y1 - y0) * self.zoom))
        # BILINEAR is fast and smooth; `reducing_gap` speeds up shrinking a lot.
        piece = piece.resize((out_w, out_h), Image.BILINEAR, reducing_gap=2.0)
        self.background = ImageTk.PhotoImage(piece)
        self.canvas.delete("bg")
        sx, sy = self.to_screen(x0, y0)
        self.canvas.create_image(sx, sy, image=self.background, anchor="nw", tags=("bg", "world"))
        self.canvas.tag_lower("bg")

    def sprite(self, n, glow=1.0):
        """The picture for idea n's star (made once, then reused)."""
        idea = self.ideas[n]
        # crc32 turns text into a number that's always the same for the same
        # text (Python's own hash() changes every run), so colours stay put.
        colour = art.STAR_COLOURS[zlib.crc32(idea["created"].encode()) % len(art.STAR_COLOURS)]
        title, text = title_and_text(idea)
        radius = 2.6 + min(len(title) + len(text), 200) / 110   # longer ideas: a bit bigger
        radius *= 0.85 + 0.25 * min(1.0, self.zoom / 0.6)        # a little bigger when zoomed in
        key = (colour, round(radius, 1), glow)
        if key not in self.sprites:
            self.sprites[key] = ImageTk.PhotoImage(art.star_sprite(colour, radius, glow))
        return self.sprites[key]

    def draw_stars(self):
        self.canvas.delete("star", "label", "ring")
        self.star_items.clear()
        for n in range(len(self.ideas)):
            sx, sy = self.to_screen(*art.idea_position(n))
            glow = 1.5 if n in (self.hovered, self.selected) else 1.0
            item = self.canvas.create_image(sx, sy, image=self.sprite(n, glow),
                                            tags=("star", "world"))
            self.star_items[item] = n
        if self.selected is not None:
            self.draw_ring(self.selected)
        if self.hovered is not None:
            self.draw_label(self.hovered)

    def draw_ring(self, n):
        """A thin circle around the selected star."""
        sx, sy = self.to_screen(*art.idea_position(n))
        self.canvas.create_oval(sx - 14, sy - 14, sx + 14, sy + 14, outline="#8b9099",
                                width=1, tags=("ring", "world"))

    def draw_label(self, n):
        """A small dark label with the idea's title, next to the star."""
        title, _ = title_and_text(self.ideas[n])
        if len(title) > 60:
            title = title[:57] + "…"
        sx, sy = self.to_screen(*art.idea_position(n))
        text = self.canvas.create_text(sx + 18, sy - 14, text=title, anchor="sw", fill=TEXT,
                                       font=(FONT, 10), tags=("label", "world"))
        x1, y1, x2, y2 = self.canvas.bbox(text)
        box = rounded_rectangle(self.canvas, x1 - 9, y1 - 5, x2 + 9, y2 + 5, 8,
                                fill=CARD_BG, outline=CARD_EDGE, tags=("label", "world"))
        self.canvas.tag_lower(box, text)

    def draw_overlay(self):
        """Things that stay fixed on the screen: the hint line and the idea card."""
        self.canvas.delete("ui")
        w, h = self.size()
        count = len(self.ideas)
        if count == 0:
            self.canvas.create_text(w / 2, h / 2, fill=SOFT_TEXT, font=(FONT, 14), justify="center",
                                    text="No ideas yet.\nPress Ctrl+Alt+I to catch your first one.",
                                    tags="ui")
        hint = (f"{count} idea{'s' if count != 1 else ''}     scroll to zoom  ·  drag to move  ·  "
                "click a star to read")
        self.canvas.create_text(18, h - 16, text=hint, anchor="sw", fill=DIM_TEXT,
                                font=(FONT, 9), tags="ui")
        if self.selected is not None:
            self.draw_card(self.selected)

    def draw_card(self, n):
        """The card on the right with the whole idea."""
        w, _ = self.size()
        idea = self.ideas[n]
        title, text = title_and_text(idea)
        width = 340
        left, top, pad = w - width - 24, 24, 20
        inner = width - 2 * pad
        y = top + pad
        items = []
        when = idea["created"].replace("T", "   ")[:-3]   # hide the seconds
        items.append(self.canvas.create_text(left + pad, y, text=when, anchor="nw",
                                             fill=DIM_TEXT, font=(FONT, 9), tags="ui"))
        y = self.canvas.bbox(items[-1])[3] + 8
        items.append(self.canvas.create_text(left + pad, y, text=title, anchor="nw", width=inner,
                                             fill=TEXT, font=(FONT + " Semibold", 15), tags="ui"))
        y = self.canvas.bbox(items[-1])[3] + 10
        if text:
            items.append(self.canvas.create_text(left + pad, y, text=text, anchor="nw",
                                                 width=inner, fill=SOFT_TEXT, font=(FONT, 11),
                                                 tags="ui"))
            y = self.canvas.bbox(items[-1])[3]
        bottom = y + pad
        # The close button "×" in the top-right corner of the card.
        close = self.canvas.create_text(left + width - 16, top + 14, text="×", anchor="ne",
                                        fill=DIM_TEXT, font=(FONT, 14), tags=("ui", "close"))
        card = rounded_rectangle(self.canvas, left, top, left + width, bottom, 14,
                                 fill=CARD_BG, outline=CARD_EDGE, tags=("ui", "card"))
        self.canvas.tag_lower(card, items[0])
        self.canvas.tag_raise(close)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------
    def star_under_mouse(self, event):
        """Which idea's star is under the mouse (or None)."""
        for item in self.canvas.find_overlapping(event.x - 4, event.y - 4, event.x + 4, event.y + 4):
            if item in self.star_items:
                n = self.star_items[item]
                sx, sy = self.to_screen(*art.idea_position(n))
                if abs(sx - event.x) <= 10 and abs(sy - event.y) <= 10:
                    return n
        return None

    def on_motion(self, event):
        if self.drag_start:
            return
        n = self.star_under_mouse(event)
        if n != self.hovered:
            self.hovered = n
            self.canvas.config(cursor="hand2" if n is not None else "")
            self.draw_stars()

    def on_wheel(self, event):
        """Zoom in or out, keeping the point under the mouse in place."""
        factor = 1.2 if event.delta > 0 else 1 / 1.2
        wx, wy = self.to_world(event.x, event.y)       # the world point under the mouse
        self.zoom *= factor
        self.keep_in_bounds()
        # Move the view so that same world point is under the mouse again.
        self.offset = (event.x - wx * self.zoom, event.y - wy * self.zoom)
        self.redraw()

    def on_press(self, event):
        self.drag_start = (event.x, event.y)
        self.drag_last = (event.x, event.y)
        self.dragged = False

    def on_drag(self, event):
        dx, dy = event.x - self.drag_last[0], event.y - self.drag_last[1]
        if abs(event.x - self.drag_start[0]) + abs(event.y - self.drag_start[1]) > 4:
            self.dragged = True
        if self.dragged:
            # Just slide everything in the "world" (fast); the overlay stays put.
            # The background is re-cut only when the drag ends.
            self.canvas.move("world", dx, dy)
            self.offset = (self.offset[0] + dx, self.offset[1] + dy)
            self.canvas.config(cursor="fleur")
        self.drag_last = (event.x, event.y)

    def on_release(self, event):
        was_drag = self.dragged
        self.drag_start = None
        self.canvas.config(cursor="")
        if was_drag:
            self.redraw()
            return
        # A click (not a drag): on the card's ×, on a star, or on empty space?
        hit = self.canvas.find_withtag("current")
        if hit and "close" in self.canvas.gettags(hit[0]):
            self.selected = None
        elif hit and "card" in self.canvas.gettags(hit[0]):
            return                                   # clicks on the card do nothing
        else:
            self.selected = self.star_under_mouse(event)
        self.draw_stars()
        self.draw_overlay()

    def on_escape(self, event):
        if self.selected is not None:
            self.selected = None
            self.draw_stars()
            self.draw_overlay()
        else:
            self.root.destroy()

    # ------------------------------------------------------------------
    # New ideas
    # ------------------------------------------------------------------
    def check_for_new_ideas(self):
        """
        Runs once a second. If ideas.jsonl changed (you saved an idea with
        Ctrl+Alt+I while the map is open), reload it and show the new star.
        """
        stamp = file_stamp(self.path)
        if stamp != self.stamp:
            self.stamp = stamp
            old_count = len(self.ideas)
            self.ideas = load_ideas(self.path)
            if self.selected is not None and self.selected >= len(self.ideas):
                self.selected = None
            if len(self.ideas) > old_count:
                self.welcome_new_star(len(self.ideas) - 1)
            else:
                self.redraw()
        # after() = "run this again in 1 second". Tkinter sleeps in between.
        self.root.after(CHECK_EVERY_MS, self.check_for_new_ideas)

    def welcome_new_star(self, n):
        """Open the new idea's card, make sure it's on screen, and pulse a ring around it."""
        self.selected = n
        wx, wy = art.idea_position(n)
        w, h = self.size()
        sx, sy = self.to_screen(wx, wy)
        if not (40 < sx < w - 400 and 40 < sy < h - 40):   # off screen or behind the card
            self.offset = ((w - 380) / 2 - wx * self.zoom, h / 2 - wy * self.zoom)
        self.redraw()
        self.pulse(n, 0)

    def pulse(self, n, frame):
        """
        An expanding, fading ring: drawn 30 times, about 33 ms apart (1 second).
        This little animation is the only time the map uses CPU without you
        touching it, and it stops by itself.
        """
        self.canvas.delete("pulse")
        if frame >= 30 or n >= len(self.ideas):
            return
        sx, sy = self.to_screen(*art.idea_position(n))
        r = 10 + frame * 2.2
        fade = 1 - frame / 30
        grey = int(40 + 180 * fade)
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, width=2,
                                outline=f"#{grey:02x}{grey:02x}{grey:02x}", tags=("pulse", "world"))
        self.root.after(33, self.pulse, n, frame + 1)


def main():
    # If a file was given after "python map.py", use it; otherwise use the real ideas.
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IDEAS_FILE
    GalaxyMap(path).root.mainloop()


if __name__ == "__main__":
    main()
