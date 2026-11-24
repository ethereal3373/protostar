"""
map.py — the galaxy map: every saved idea is a star.

Run it with:   python map.py
(For testing you can give it another ideas file:  python map.py some_file.jsonl)

  - Move the mouse over a star to see its idea.
  - Click a star to show the full idea at the bottom.
  - Esc closes the map.

This is a SEPARATE program from protostar.py. It only runs while you look
at it, so it doesn't add anything to the always-running part.

How the stars are placed
------------------------
Ideas are placed on a spiral, like seeds in a sunflower:
  - idea number n turns by the "golden angle" (about 137.5 degrees) from the last one
  - and sits a little further out (distance grows with the square root of n)
This spreads stars evenly without any overlapping, and it looks like a
galaxy. The oldest idea sits at the centre; new ideas appear at the edge.
The same ideas always land in the same place, so the map stays familiar.
"""

import json
import math
import random
import sys
import tkinter as tk
from pathlib import Path

from protostar import IDEAS_FILE  # reuse the same file location as the capture box

GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))  # about 2.4 radians = 137.5 degrees

BACKGROUND = "#07071a"
STAR_COLOURS = ["#ffffff", "#cfd8ff", "#ffe9c4", "#bcd2ff", "#ffd6f5"]
TEXT_COLOUR = "#f0f0ff"


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


class GalaxyMap:
    def __init__(self, ideas):
        self.ideas = ideas
        self.root = tk.Tk()
        self.root.title(f"Protostar — {len(ideas)} ideas")
        self.root.geometry("900x650")
        self.root.configure(bg=BACKGROUND)

        # A Canvas is a Tkinter area you can draw shapes on.
        self.canvas = tk.Canvas(self.root, bg=BACKGROUND, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # A text strip at the bottom for the clicked idea.
        # height=3 keeps it always 3 lines tall: if it grew when you click a
        # star, the map above would shrink and every star would jump.
        self.details = tk.Label(self.root, bg=BACKGROUND, fg=TEXT_COLOUR,
                                font=("Segoe UI", 12), wraplength=860, height=3,
                                justify="left", anchor="w", padx=20, pady=10,
                                text="Click a star to read its idea.")
        self.details.pack(fill="x")

        self.star_to_idea = {}  # canvas item id -> idea (so we know which star was clicked)

        # "<Configure>" fires when the window appears or is resized:
        # then we redraw everything to fit the new size.
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.root.bind("<Escape>", lambda event: self.root.destroy())

    def draw(self):
        c = self.canvas
        c.delete("all")  # wipe the canvas before drawing again
        self.star_to_idea.clear()
        width, height = c.winfo_width(), c.winfo_height()
        cx, cy = width / 2, height / 2

        # 1. Faint background dust (pure decoration). A fixed "seed" makes
        #    random() give the same numbers every time, so the dust doesn't jump.
        rng = random.Random(42)
        for _ in range(250):
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            shade = rng.choice(["#1c1c3a", "#24244a", "#2e2e5a"])
            c.create_oval(x, y, x + 1.5, y + 1.5, fill=shade, outline="")

        if not self.ideas:
            c.create_text(cx, cy, fill=TEXT_COLOUR, font=("Segoe UI", 16),
                          text="No ideas yet.\nPress Ctrl+Alt+I to catch your first one.",
                          justify="center")
            return

        # 2. The ideas, on the sunflower spiral.
        # "spacing" is chosen so the outermost star just fits in the window.
        spacing = 0.9 * min(width, height) / 2 / math.sqrt(len(self.ideas) + 1)
        for n, idea in enumerate(self.ideas):
            angle = n * GOLDEN_ANGLE
            distance = spacing * math.sqrt(n + 0.5)
            x = cx + distance * math.cos(angle)
            y = cy + distance * math.sin(angle)

            # Longer ideas make slightly bigger stars (between 3 and 7 pixels).
            size = 3 + min(len(idea["text"]), 120) / 30
            colour = STAR_COLOURS[n % len(STAR_COLOURS)]

            # A soft glow behind the star, then the star itself.
            c.create_oval(x - size * 2.2, y - size * 2.2, x + size * 2.2, y + size * 2.2,
                          fill="#151538", outline="")
            star = c.create_oval(x - size, y - size, x + size, y + size,
                                 fill=colour, outline="")
            self.star_to_idea[star] = idea

            # tag_bind = "when this one shape is hovered/clicked, run this".
            c.tag_bind(star, "<Enter>", lambda e, i=idea, sx=x, sy=y: self.show_tooltip(i, sx, sy))
            c.tag_bind(star, "<Leave>", lambda e: c.delete("tooltip"))
            c.tag_bind(star, "<Button-1>", lambda e, i=idea: self.show_details(i))

    def show_tooltip(self, idea, x, y):
        text = idea["text"]
        if len(text) > 60:
            text = text[:57] + "..."
        self.canvas.config(cursor="hand2")
        label = self.canvas.create_text(x + 12, y - 12, text=text, anchor="sw",
                                        fill=TEXT_COLOUR, font=("Segoe UI", 11), tags="tooltip")
        # Draw a dark box behind the text so it's readable over other stars.
        x1, y1, x2, y2 = self.canvas.bbox(label)
        box = self.canvas.create_rectangle(x1 - 6, y1 - 3, x2 + 6, y2 + 3,
                                           fill="#1e1e44", outline="#3a3a7a", tags="tooltip")
        self.canvas.tag_lower(box, label)  # put the box under the text

    def show_details(self, idea):
        self.details.config(text=f"{idea['created'].replace('T', '  ')}\n{idea['text']}")


def main():
    # If a file was given after "python map.py", use it; otherwise use the real ideas.
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else IDEAS_FILE
    GalaxyMap(load_ideas(path)).root.mainloop()


if __name__ == "__main__":
    main()
