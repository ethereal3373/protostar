"""
protostar.py — the always-running part of Protostar.

Run it with:   python protostar.py

  Ctrl+Alt+I -> a small box pops up. Type your idea:
                  Enter = save it,  Esc = close without saving
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
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path

import hotkey

# Ideas are saved next to this file, in the "ideas" folder.
# That folder is listed in .gitignore, so it never goes to GitHub.
IDEAS_FOLDER = Path(__file__).parent / "ideas"
IDEAS_FILE = IDEAS_FOLDER / "ideas.jsonl"


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


class CaptureBox:
    """The small floating box where you type an idea."""

    WIDTH = 520
    HEIGHT = 56

    def __init__(self):
        # The "root" is the main Tkinter window. We build it once at startup
        # and then just hide/show it — faster than rebuilding it every time.
        self.root = tk.Tk()
        self.root.title("Protostar")
        self.root.overrideredirect(True)          # no title bar or borders
        self.root.attributes("-topmost", True)    # stays above other windows
        self.root.configure(bg="#14142b", padx=10, pady=10)

        # The text field you type into.
        self.entry = tk.Entry(
            self.root,
            font=("Segoe UI", 14),
            bg="#14142b", fg="#f0f0ff",
            insertbackground="#f0f0ff",  # colour of the blinking cursor
            relief="flat",
        )
        self.entry.pack(fill="both", expand=True)

        # Keys inside the box.
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<Escape>", lambda event: self.hide())

        # Messages that will come from the shortcut thread.
        self.root.bind("<<Capture>>", lambda event: self.show())
        self.root.bind("<<Quit>>", lambda event: self.root.destroy())

        self.hide()  # start hidden

    def show(self):
        # Put the box in the middle of the screen, slightly above centre.
        x = (self.root.winfo_screenwidth() - self.WIDTH) // 2
        y = self.root.winfo_screenheight() // 3
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.root.deiconify()      # make it visible
        self.root.lift()
        self.root.focus_force()    # take the keyboard so you can type at once
        self.entry.focus_set()

    def hide(self):
        self.entry.delete(0, "end")  # clear the text for next time
        self.root.withdraw()         # make it invisible (it still exists)

    def on_enter(self, event):
        text = self.entry.get().strip()
        if text:                     # don't save empty ideas
            save_idea(text)
        self.hide()


def main():
    box = CaptureBox()

    def run_listener():
        # This function runs in the second thread.
        # event_generate sends a message to the window, which lives in the
        # main thread. It's the safe way for a thread to talk to Tkinter.
        try:
            hotkey.listen(on_capture=lambda: box.root.event_generate("<<Capture>>", when="tail"))
        except OSError as error:
            # Usually: the shortcut is already taken (for example, another
            # copy of Protostar is already running). Without the shortcut
            # Protostar is useless, so we say why and close.
            print("Error:", error)
        # listen() returns when Ctrl+Alt+Q is pressed -> ask the window to close.
        box.root.event_generate("<<Quit>>", when="tail")

    # daemon=True: if the window closes, this thread won't keep the program alive.
    listener = threading.Thread(target=run_listener, daemon=True)
    # Start the thread only once mainloop() is running ("after_idle" = as soon
    # as the window is ready). Before that, the window can't receive messages.
    box.root.after_idle(listener.start)

    print("Protostar is running. Ctrl+Alt+I = new idea, Ctrl+Alt+Q = quit.")
    box.root.mainloop()  # sleep until something happens in the window
    print("Bye!")


if __name__ == "__main__":
    main()
