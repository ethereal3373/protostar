"""
protostar.py — the always-running part of Protostar.

Run it with:   python protostar.py

  Ctrl+Alt+I -> a note pops up. Write your idea:
                  Enter = save it,  Shift+Enter = new line,
                  Esc = close (your draft is kept for next time)
  Ctrl+Alt+M -> open the galaxy map (a separate program, see map.py)
  Ctrl+Alt+Q -> quit Protostar

How the pieces fit together
---------------------------
Two things need to "wait" at the same time:
  1. the shortcut listener (hotkey.py) waits for Windows to say "a shortcut was pressed"
  2. the window (Tkinter) waits for you to type, click, press Enter...

One program can normally only wait for one thing at a time. So we use a
THREAD: a second line of work running inside the same program. The
listener sleeps in its own thread, the window sleeps in the main thread,
and when a shortcut arrives, the listener sends a small message
("<<Capture>>") over to the window. Both sides sleep while nothing
happens, so CPU stays at ~0%.
"""

import json
import subprocess  # lets us start another program (the map)
import sys
import threading
import tkinter as tk
from tkinter import messagebox  # ready-made popup windows (errors, warnings...)
from datetime import datetime
from pathlib import Path

import hotkey

# Ideas are saved next to this file, in the "ideas" folder.
# That folder is listed in .gitignore, so it never goes to GitHub.
IDEAS_FOLDER = Path(__file__).parent / "ideas"
IDEAS_FILE = IDEAS_FOLDER / "ideas.jsonl"

# The map window always has this exact title, so we can find it if it's already open.
MAP_TITLE = "Protostar — Galaxy map"


def save_idea(text):
    """
    Add one idea to the end of ideas.jsonl.

    The file uses "JSON Lines": one idea per line, each written as JSON
    (a simple text format for data). Adding a line to the end is fast and
    never touches the ideas already saved.
    """
    IDEAS_FOLDER.mkdir(exist_ok=True)  # create the folder the first time
    idea = {"created": datetime.now().isoformat(timespec="seconds"), "text": text}
    with open(IDEAS_FILE, "a", encoding="utf-8") as f:  # "a" = append
        f.write(json.dumps(idea, ensure_ascii=False) + "\n")


# --- Colours of the capture window (dark grey / black, white text) ---
WINDOW_BG = "#1c1c1c"   # the note itself
BORDER = "#3a3a3a"      # thin outline around the window
TEXT = "#ffffff"        # what you type
HINT = "#8a8a8a"        # small grey helper text
FONT = ("Segoe UI", 11)
SMALL_FONT = ("Segoe UI", 9)


class CaptureBox:
    """The floating note where you write an idea."""

    WIDTH = 460
    HEIGHT = 320

    def __init__(self):
        # The "root" is the main Tkinter window. We build it once at startup
        # and then just hide/show it — faster than rebuilding it every time.
        self.root = tk.Tk()
        self.root.title("Protostar")
        self.root.overrideredirect(True)          # no Windows title bar
        self.root.attributes("-topmost", True)    # stays above other windows
        # The window's own background is the border colour; the note sits
        # inside it with 1 pixel of space, which looks like a thin outline.
        self.root.configure(bg=BORDER, padx=1, pady=1)

        # A Frame is an invisible box that groups other widgets together.
        note = tk.Frame(self.root, bg=WINDOW_BG)
        note.pack(fill="both", expand=True)

        # --- Top bar: title. You can drag the window by it. ---
        header = tk.Label(note, text="New idea", bg=WINDOW_BG, fg=HINT,
                          font=SMALL_FONT, anchor="w", padx=14, pady=8)
        header.pack(fill="x")
        header.bind("<ButtonPress-1>", self.start_drag)
        header.bind("<B1-Motion>", self.drag)

        # --- Bottom bar: reminder of the keys. ---
        # (packed before the text area so it always keeps its place at the bottom)
        footer = tk.Label(note, bg=WINDOW_BG, fg=HINT, font=SMALL_FONT,
                          anchor="w", padx=14, pady=8,
                          text="Enter  save    ·    Shift+Enter  new line    ·    Esc  close")
        footer.pack(side="bottom", fill="x")

        # --- The writing area. ---
        # A Text widget is like Entry, but with many lines (a mini notepad).
        self.text = tk.Text(
            note,
            font=FONT, bg=WINDOW_BG, fg=TEXT,
            insertbackground=TEXT,     # colour of the blinking cursor
            selectbackground="#444444",
            relief="flat", borderwidth=0, highlightthickness=0,
            wrap="word",               # long lines wrap at whole words
            padx=14, pady=4,
            undo=True,                 # Ctrl+Z works
        )
        self.text.pack(fill="both", expand=True)

        # Keys inside the note.
        self.text.bind("<Return>", self.on_enter)
        # Shift+Enter: do nothing special, so Tkinter's normal "new line" happens.
        self.text.bind("<Shift-Return>", lambda event: None)
        self.text.bind("<Escape>", lambda event: self.hide())

        # Messages that will come from the shortcut thread.
        self.root.bind("<<Capture>>", lambda event: self.show())
        self.root.bind("<<Quit>>", lambda event: self.root.destroy())

        self.position = None  # where the window is; None = centre of the screen
        self.hide()           # start hidden

    def show(self):
        if self.position is None:
            # First time: middle of the screen, a bit above centre.
            x = (self.root.winfo_screenwidth() - self.WIDTH) // 2
            y = (self.root.winfo_screenheight() - self.HEIGHT) // 3
            self.position = (x, y)
        x, y = self.position
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.root.deiconify()      # make it visible
        self.root.lift()
        self.root.focus_force()    # take the keyboard so you can type at once
        self.text.focus_set()
        self.text.mark_set("insert", "end")  # cursor at the end of any draft

    def hide(self):
        # Note: the text is NOT cleared here. If you press Esc by mistake,
        # your draft is still there the next time you press Ctrl+Alt+I.
        self.root.withdraw()       # make it invisible (it still exists)

    def on_enter(self, event):
        # "1.0" means line 1, character 0 (the very start); "end" is the end.
        text = self.text.get("1.0", "end").strip()
        if text:                   # don't save empty ideas
            save_idea(text)
        self.text.delete("1.0", "end")       # clear it for the next idea
        self.text.edit_reset()               # forget the undo history too
        self.hide()
        return "break"  # stop Tkinter from ALSO adding a new line

    # --- Dragging the window by its top bar ---
    def start_drag(self, event):
        # Remember where inside the window you grabbed it.
        self.grab = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event):
        x = event.x_root - self.grab[0]
        y = event.y_root - self.grab[1]
        self.root.geometry(f"+{x}+{y}")
        self.position = (x, y)  # remember it for next time


def open_map():
    """
    Open the galaxy map (map.py) as a separate program.
    If it's already open, bring that window to the front instead of
    opening a second one.
    """
    window = hotkey.user32.FindWindowW(None, MAP_TITLE)  # look for it by its title
    if window:
        hotkey.user32.ShowWindow(window, 9)         # 9 = "restore" if minimized
        hotkey.user32.SetForegroundWindow(window)   # bring it to the front
        return
    # pythonw.exe = Python without a terminal window (it sits next to python.exe).
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    map_file = Path(__file__).parent / "map.py"
    # Popen starts the map and returns immediately: we don't wait for it.
    # The map is its own process, so closing it frees all its memory.
    subprocess.Popen([pythonw, map_file], cwd=map_file.parent)


def main():
    box = CaptureBox()

    def run_listener():
        # This function runs in the second thread.
        # event_generate sends a message to the window, which lives in the
        # main thread. It's the safe way for a thread to talk to Tkinter.
        try:
            hotkey.listen(
                on_capture=lambda: box.root.event_generate("<<Capture>>", when="tail"),
                on_map=open_map,  # this one doesn't touch Tkinter, so it can run here
            )
        except OSError as error:
            # Usually: the shortcut is already taken (for example, another
            # copy of Protostar is already running). Without the shortcut
            # Protostar is useless, so we tell the window to show why and close.
            problems.append(str(error))
            box.root.event_generate("<<HotkeyError>>", when="tail")
            return
        # listen() returns when Ctrl+Alt+Q is pressed -> ask the window to close.
        box.root.event_generate("<<Quit>>", when="tail")

    # The thread puts its error message here so the window can read it.
    problems = []

    def show_error(event):
        # When Protostar runs in the background there is no terminal, so
        # print() shows nothing. A popup window is the only way to tell you.
        print("Error:", problems[0])
        messagebox.showerror("Protostar can't start", problems[0], parent=box.root)
        box.root.destroy()

    box.root.bind("<<HotkeyError>>", show_error)

    # daemon=True: if the window closes, this thread won't keep the program alive.
    listener = threading.Thread(target=run_listener, daemon=True)
    # Start the thread only once mainloop() is running ("after_idle" = as soon
    # as the window is ready). Before that, the window can't receive messages.
    box.root.after_idle(listener.start)

    print("Protostar is running. Ctrl+Alt+I = new idea, Ctrl+Alt+M = map, Ctrl+Alt+Q = quit.")
    box.root.mainloop()  # sleep until something happens in the window
    print("Bye!")


if __name__ == "__main__":
    main()
