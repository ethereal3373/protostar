"""
widgets.py — the building blocks of Protostar's panels, with rounded corners.

Tkinter's own boxes (Frame, Label) are always sharp rectangles. To get soft,
rounded shapes (like in the Claude app), we draw them ourselves:

  - rounded_image(): a rounded rectangle made with Pillow. It's drawn 4x
    bigger and then shrunk, so the curves come out smooth instead of jagged
    ("anti-aliasing"). Each size/colour is made once and kept (a "cache").
  - Row: a clickable row (an idea, a folder, a search result). It's a small
    Canvas: the rounded shape appears behind the text when you hover or
    select it. Everything is drawn on one canvas, so there are no child
    widgets fighting over mouse events.
  - RoundedBox: a text field (Entry or Text) sitting on a rounded background.
  - ScrollArea, small_button: as before.
"""

import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

_images = {}


def rounded_image(width, height, radius, fill, background, outline=None):
    """A smooth rounded rectangle as a Tkinter image (made once per size/colour)."""
    # (The window's id is part of the key: pictures belong to one Tkinter window,
    # so a new window must make its own.)
    key = (id(tk._default_root), width, height, radius, fill, background, outline)
    if key not in _images:
        scale = 4
        big = Image.new("RGB", (width * scale, height * scale), background)
        draw = ImageDraw.Draw(big)
        box = (0, 0, width * scale - 1, height * scale - 1)
        if outline:
            draw.rounded_rectangle(box, radius * scale, fill=outline)
            inset = scale     # a 1-pixel outline
            box = (inset, inset, width * scale - 1 - inset, height * scale - 1 - inset)
            draw.rounded_rectangle(box, (radius - 1) * scale, fill=fill)
        else:
            draw.rounded_rectangle(box, radius * scale, fill=fill)
        small = big.resize((width, height), Image.LANCZOS)
        _images[key] = ImageTk.PhotoImage(small)
    return _images[key]


class Row(tk.Canvas):
    """
    A clickable row with a rounded highlight.

    Fill it with add(): pieces of text on the left (one after another) or on
    the right, or "lines" stacked under each other (for longer, wrapping text).
    """

    def __init__(self, parent, bg, on_click=None, height=30, radius=8,
                 hover="#2a2927", selected_colour="#34332f", selected=False, padx=10):
        super().__init__(parent, bg=bg, height=height, highlightthickness=0, borderwidth=0,
                         cursor="hand2" if on_click else "")
        self.bg, self.hover_colour, self.selected_colour = bg, hover, selected_colour
        self.radius, self.padx, self.base_height = radius, padx, height
        self.selected = selected
        self.hovering = False
        self.items = []        # (kind, text, font, colour, extra)
        self.on_click = on_click
        self.bind("<Configure>", lambda e: self.draw())
        if on_click:
            self.bind("<Enter>", lambda e: self.set_hover(True))
            self.bind("<Leave>", lambda e: self.set_hover(False))
            self.bind("<Button-1>", lambda e: on_click())

    def add(self, text, side="left", font=None, colour="#bdbbb3", gap=6):
        self.items.append(("side", text, font, colour, (side, gap)))
        return self

    def add_line(self, text, font=None, colour="#bdbbb3", gap=2):
        """A line of text under the previous one, wrapping to the row's width."""
        self.items.append(("line", text, font, colour, gap))
        return self

    def set_hover(self, on):
        self.hovering = on
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 4:
            return
        # 1. The text, laid out first so we know how tall the row must be.
        lines = [i for i in self.items if i[0] == "line"]
        if lines:
            y = 7
            for _, text, font, colour, gap in lines:
                y += gap
                item = self.create_text(self.padx, y, text=text, font=font, fill=colour,
                                        anchor="nw", width=w - 2 * self.padx, tags="text")
                y = self.bbox(item)[3]
            height = max(self.base_height, y + 8)
            if int(self.cget("height")) != height:
                self.configure(height=height)
        else:
            height = self.base_height
            left, right = self.padx, w - self.padx
            for _, text, font, colour, (side, gap) in self.items:
                if side == "left":
                    item = self.create_text(left, height / 2, text=text, font=font, fill=colour,
                                            anchor="w", tags="text")
                    left = self.bbox(item)[2] + gap
                else:
                    item = self.create_text(right, height / 2, text=text, font=font, fill=colour,
                                            anchor="e", tags="text")
                    right = self.bbox(item)[0] - gap
        # 2. The rounded highlight behind the text (when hovered or selected).
        fill = self.selected_colour if self.selected else (self.hover_colour if self.hovering else None)
        if fill:
            image = rounded_image(w, int(height), self.radius, fill, self.bg)
            self.create_image(0, 0, image=image, anchor="nw")
            self.tag_raise("text")


class RoundedBox(tk.Canvas):
    """A text field on a rounded background: kind="entry" (one line) or "text" (several)."""

    def __init__(self, parent, bg, fill="#2a2927", outline="#34332f", height=34, radius=10,
                 kind="entry", lines=4, focus_outline=None, **field_options):
        super().__init__(parent, bg=bg, height=height, highlightthickness=0, borderwidth=0)
        self.bg, self.fill, self.radius = bg, fill, radius
        self.outline = self.normal_outline = outline
        self.focus_outline = focus_outline or outline
        options = dict(bg=fill, relief="flat", borderwidth=0, highlightthickness=0)
        options.update(field_options)
        if kind == "text":
            self.field = tk.Text(self, height=lines, wrap="word", undo=True, **options)
        else:
            self.field = tk.Entry(self, **options)
        self.window = self.create_window(10, 0, window=self.field, anchor="nw")
        self.bind("<Configure>", lambda e: self.draw())
        self.field.bind("<Configure>", lambda e: self.draw(), add="+")
        # The outline lights up while you type in the box.
        self.field.bind("<FocusIn>", lambda e: self.set_outline(self.focus_outline), add="+")
        self.field.bind("<FocusOut>", lambda e: self.set_outline(self.normal_outline), add="+")

    def set_outline(self, colour):
        self.outline = colour
        self.draw()

    def draw(self):
        w = self.winfo_width()
        if w < 24:
            return
        field_h = self.field.winfo_reqheight()
        h = field_h + 14
        if int(self.cget("height")) != h:
            self.configure(height=h)
        self.delete("bg")
        image = rounded_image(w, h, self.radius, self.fill, self.bg, self.outline)
        self.create_image(0, 0, image=image, anchor="nw", tags="bg")
        self.tag_lower("bg")
        self.coords(self.window, 11, 7)
        self.itemconfigure(self.window, width=w - 22)


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


def small_button(parent, text, command, colour, bg, font, hover_colour="#eeede9"):
    """A little text button (like a link) that brightens when hovered."""
    label = tk.Label(parent, text=text, bg=bg, fg=colour, font=font, cursor="hand2")
    label.bind("<Enter>", lambda e: label.config(fg=hover_colour))
    label.bind("<Leave>", lambda e: label.config(fg=colour))
    label.bind("<Button-1>", lambda e: command())
    return label
