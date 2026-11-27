"""
protostar.py — the always-running part of Protostar.

Run it with:   python protostar.py

  Ctrl+Alt+I -> a note pops up. Write your idea (the first line is its title):
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

import ctypes      # talk to Windows directly (used for rounded corners)
import json
import subprocess  # lets us start another program (the map)
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox  # ready-made popup windows (errors, warnings...)
from datetime import datetime
from pathlib import Path

import autoformat
import reminders
import fonts
import hotkey
import settings

# Ideas are saved next to this file, in the "ideas" folder.
# That folder is listed in .gitignore, so it never goes to GitHub.
IDEAS_FOLDER = Path(__file__).parent / "ideas"
IDEAS_FILE = IDEAS_FOLDER / "ideas.jsonl"

# The main window (map.py) always has this exact title, so we can find it if
# it's already open. (The capture note uses a different, invisible title.)
MAP_TITLE = "Protostar"


def save_idea(title, text=""):
    """
    Add one idea (a title, plus optional longer text) to the end of ideas.jsonl.

    The file uses "JSON Lines": one idea per line, each written as JSON
    (a simple text format for data). Adding a line to the end is fast and
    never touches the ideas already saved.
    """
    IDEAS_FOLDER.mkdir(exist_ok=True)  # create the folder the first time
    idea = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "text": text,
    }
    with open(IDEAS_FILE, "a", encoding="utf-8") as f:  # "a" = append
        f.write(json.dumps(idea, ensure_ascii=False) + "\n")


def save_note(parent, text):
    """
    Add a note to an existing idea. `parent` is that idea's "created" time,
    which works as its name tag. (The note's own time includes microseconds,
    so two notes never get the same name tag.)
    """
    IDEAS_FOLDER.mkdir(exist_ok=True)
    note = {"created": datetime.now().isoformat(), "parent": parent, "text": text}
    with open(IDEAS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")


def recent_ideas(count):
    """
    The newest `count` ideas as (created, title), newest first. Read only
    when the menu is opened, so the always-running part keeps nothing in memory.
    """
    if not IDEAS_FILE.exists():
        return []
    ideas = []
    with open(IDEAS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "parent" in record or "link" in record:
                continue                      # notes and links aren't ideas
            title = record.get("title", record.get("text", "").partition("\n")[0])
            ideas.append((record["created"], title))
    ideas.sort(reverse=True)                  # newest first
    return ideas[:count]


# --- Colours of the capture window: the same theme as the main app (Settings) ---
SETTINGS = settings.load()
_THEME = settings.theme(SETTINGS)
WINDOW_BG = _THEME["sidebar"]       # the note itself
BORDER = _THEME["input_edge"]       # thin outline around the window
TEXT = _THEME["text"]               # what you type
HINT = _THEME["dim"]                # small grey helper text
MENU_BG, MENU_ACTIVE = _THEME["input"], _THEME["selected"]
# Inter, the same font as the main app (loaded only for this program, see fonts.py).
# (Settings can switch to Windows' own Segoe UI, and change the keys below.)
_REGULAR, _SEMIBOLD = fonts.load() if SETTINGS["font"] == "inter" else ("Segoe UI", "Segoe UI Semibold")
SAVE_WITH_CTRL = SETTINGS["capture_save"] == "ctrl_enter"
FONT = (_REGULAR, 11)
SMALL_FONT = (_REGULAR, 9)


TITLE_FONT = (_SEMIBOLD, 14)


def round_corners(window):
    """
    Ask Windows 11 to give this window rounded corners and a thin grey outline.

    Tkinter can't do this by itself, so we ask DWM (the "Desktop Window
    Manager", the part of Windows that draws every window on screen).
    Returns True if it worked (Windows 11), False otherwise (e.g. Windows 10).
    """
    hwnd = int(window.wm_frame(), 16)  # Windows' ID number for our window
    dwm = ctypes.WinDLL("dwmapi")

    DWMWA_WINDOW_CORNER_PREFERENCE = 33  # "which corner style?"
    DWMWCP_ROUND = 2                      # -> "round, please"
    DWMWA_BORDER_COLOR = 34               # "which outline colour?"

    corner = ctypes.c_int(DWMWCP_ROUND)
    result = dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                       ctypes.byref(corner), ctypes.sizeof(corner))
    if result != 0:  # 0 means "OK"; anything else means "not supported"
        return False

    # Windows wants colours written as 0x00BBGGRR (blue, green, red — backwards!).
    r, g, b = int(BORDER[1:3], 16), int(BORDER[3:5], 16), int(BORDER[5:7], 16)
    colour = ctypes.c_uint(b << 16 | g << 8 | r)
    dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR,
                              ctypes.byref(colour), ctypes.sizeof(colour))
    return True


class CaptureBox:
    """
    The floating note where you write an idea.
    The first line is the idea's title (shown bigger); the rest is the text.
    """

    WIDTH = 460
    HEIGHT = 320

    def __init__(self):
        # The "root" is the main Tkinter window. We build it once at startup
        # and then just hide/show it — faster than rebuilding it every time.
        self.root = tk.Tk()
        self.root.title("Protostar capture")  # never shown (no title bar), but must differ from MAP_TITLE
        self.root.overrideredirect(True)          # no Windows title bar
        self.root.attributes("-topmost", True)    # stays above other windows

        # Thin outline: the window's background is the border colour, and the
        # note sits inside it with 1 pixel of space. (On Windows 11 we switch
        # to real rounded corners the first time the note is shown.)
        self.root.configure(bg=BORDER, padx=1, pady=1)
        self.corners_done = False

        # A Frame is an invisible box that groups other widgets together.
        note = tk.Frame(self.root, bg=WINDOW_BG)
        note.pack(fill="both", expand=True)

        # --- Top bar. You can drag the window by it. ---
        # On the left, "New idea ▾": click it to choose between writing a new
        # idea or adding a note to an idea you already have.
        header = tk.Frame(note, bg=WINDOW_BG)
        header.pack(fill="x")
        self.mode_label = tk.Label(header, bg=WINDOW_BG, fg=HINT, font=SMALL_FONT,
                                   padx=14, pady=8, cursor="hand2")
        self.mode_label.pack(side="left")
        self.mode_label.bind("<Button-1>", self.open_mode_menu)
        self.mode_label.bind("<Enter>", lambda e: self.mode_label.config(fg=TEXT))
        self.mode_label.bind("<Leave>", lambda e: self.mode_label.config(fg=HINT))
        # 🎙 on the right: Windows voice typing (speak instead of typing).
        mic = tk.Label(header, text="🎙", bg=WINDOW_BG, fg=HINT, font=SMALL_FONT, padx=14,
                       cursor="hand2")
        mic.pack(side="right")
        mic.bind("<Button-1>", lambda e: self.dictate())
        mic.bind("<Enter>", lambda e: mic.config(fg=TEXT))
        mic.bind("<Leave>", lambda e: mic.config(fg=HINT))
        grip = tk.Frame(header, bg=WINDOW_BG)        # the empty rest of the bar: drag here
        grip.pack(side="left", fill="both", expand=True)
        for widget in (header, grip):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
        self.target = None      # None = new idea; otherwise (created, title) of the idea to add a note to
        self.update_mode_label()

        # --- Bottom bar: reminder of the keys. ---
        # (packed before the text area so it always keeps its place at the bottom)
        footer = tk.Label(note, bg=WINDOW_BG, fg=HINT, font=SMALL_FONT,
                          anchor="w", padx=14, pady=8,
                          text=("Ctrl+Enter  save    ·    Enter  new line    ·    Esc  close" if SAVE_WITH_CTRL
                                else "Enter  save    ·    Shift+Enter  new line    ·    Esc  close"))
        footer.pack(side="bottom", fill="x")

        # --- The writing area. ---
        # A Text widget is like Entry, but with many lines (a mini notepad).
        self.text = tk.Text(
            note,
            font=FONT, bg=WINDOW_BG, fg=TEXT,
            insertbackground=TEXT,     # colour of the blinking cursor
            selectbackground=_THEME["selected"],
            relief="flat", borderwidth=0, highlightthickness=0,
            wrap="word",               # long lines wrap at whole words
            padx=14, pady=4,
            undo=True,                 # Ctrl+Z works
        )
        self.text.pack(fill="both", expand=True)

        # A "tag" is a name for a piece of the text that can have its own style.
        # The tag "title" = bigger font, and we keep it on line 1 only.
        self.text.tag_configure("title", font=TITLE_FONT, spacing3=6)  # spacing3 = gap below it
        # <<Modified>> fires whenever the text changes (typing, pasting, deleting...).
        self.text.bind("<<Modified>>", self.style_title)

        # Keys inside the note.
        if SAVE_WITH_CTRL:
            # Settings: Ctrl+Enter saves; Enter is a normal new line.
            self.text.bind("<Control-Return>", self.on_enter)
        else:
            self.text.bind("<Return>", self.on_enter)
            # Shift+Enter: do nothing special, so Tkinter's normal "new line" happens.
            self.text.bind("<Shift-Return>", lambda event: None)
        self.text.bind("<Escape>", lambda event: self.hide())
        # Word-style formatting: "- " becomes a bullet, capitals after a full stop.
        autoformat.attach(self.text, "<Return>" if SAVE_WITH_CTRL else "<Shift-Return>")

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
        if not self.corners_done:
            # Only now does the real Windows window exist, so we can style it.
            if round_corners(self.root):
                # Windows 11 draws the corners and outline: drop our fake one.
                self.root.configure(bg=WINDOW_BG, padx=0, pady=0)
            self.corners_done = True
        self.root.lift()
        self.root.focus_force()    # take the keyboard so you can type at once
        self.text.focus_set()
        self.text.mark_set("insert", "end")  # cursor at the end of any draft
        self.read_request()

    def read_request(self):
        """
        The main app's ⤢ button leaves a small file asking us to write a note
        for a particular idea. If it's there (and fresh), use it, then delete it.
        """
        request = IDEAS_FOLDER / "capture_request.json"
        try:
            if time.time() - request.stat().st_mtime < 10:
                wanted = json.loads(request.read_text(encoding="utf-8"))
                if Path(wanted.get("file", IDEAS_FILE)).resolve() == IDEAS_FILE.resolve():
                    self.set_target((wanted["parent"], wanted.get("title", "")))
            request.unlink()
        except (FileNotFoundError, ValueError, KeyError):
            pass

    def dictate(self):
        """Start Windows' voice typing (Win+H) in the note: the speech recognition is Windows' own."""
        self.text.focus_set()
        user32 = ctypes.WinDLL("user32")
        def press():
            for key in (0x5B, 0x48):            # Windows key + H
                user32.keybd_event(key, 0, 0, 0)
            for key in (0x48, 0x5B):
                user32.keybd_event(key, 0, 2, 0)
        self.root.after(150, press)

    def hide(self):
        # Note: the text is NOT cleared here. If you press Esc by mistake,
        # your draft is still there the next time you press Ctrl+Alt+I.
        self.root.withdraw()       # make it invisible (it still exists)

    def style_title(self, event=None):
        # Move the "title" style to wherever line 1 is right now.
        # "1.0" = line 1, character 0 (the start); "1.end" = the end of line 1.
        self.text.tag_remove("title", "1.0", "end")
        if self.target is None:          # notes have no title: no big first line
            self.text.tag_add("title", "1.0", "1.end")
        # Tell Tkinter "I've seen this change", so <<Modified>> fires next time too.
        self.text.edit_modified(False)

    # --- "New idea ▾" / "Note for … ▾" ---
    def update_mode_label(self):
        if self.target is None:
            self.mode_label.config(text="New idea  ▾")
        else:
            title = self.target[1] if len(self.target[1]) <= 32 else self.target[1][:31] + "…"
            self.mode_label.config(text=f"Note for:  {title}  ▾")

    def open_mode_menu(self, event):
        """
        A small drop-down menu: "New idea", or one of your recent ideas to add
        a note to. The menu is built only when you click (and thrown away
        after), so it costs nothing the rest of the time.
        """
        style = dict(tearoff=0, bg=MENU_BG, fg=TEXT, activebackground=MENU_ACTIVE,
                     activeforeground=TEXT, borderwidth=0, font=SMALL_FONT)
        menu = tk.Menu(self.root, **style)
        menu.add_command(label="✦  New idea", command=lambda: self.set_target(None))
        ideas = recent_ideas(15)
        if ideas:
            menu.add_separator()
            menu.add_command(label="Add a note to…", state="disabled")
            for created, title in ideas:
                shown = title if len(title) <= 40 else title[:39] + "…"
                menu.add_command(label="     " + (shown or "(no title)"),
                                 command=lambda c=created, t=title: self.set_target((c, t)))
        menu.tk_popup(self.mode_label.winfo_rootx(),
                      self.mode_label.winfo_rooty() + self.mode_label.winfo_height())

    def set_target(self, target):
        self.target = target
        self.update_mode_label()
        self.style_title()
        self.text.focus_set()

    def on_enter(self, event):
        # "end" is the very end of the text.
        everything = self.text.get("1.0", "end").strip()
        if everything and self.target is not None:
            save_note(self.target[0], everything)      # a note for an existing idea
        elif everything:           # don't save empty ideas
            # Split at the first line break: before = title, after = the text.
            title, _, body = everything.partition("\n")
            save_idea(title.strip(), body.strip())
        self.text.delete("1.0", "end")       # clear it for the next idea
        self.text.edit_reset()               # forget the undo history too
        self.set_target(None)                # next time: a new idea again
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


# ---------------------------------------------------------------------------
# Reminders: once a minute, look for deadlines coming up (see reminders.py)
# ---------------------------------------------------------------------------

CHECK_REMINDERS_MS = 60_000      # once a minute: almost no work, so ~0% CPU


class Reminders:
    """Checks for due reminders and shows them as small pop-ups in the corner."""

    def __init__(self, root):
        self.root = root
        self.stamp = None
        self.ideas = []           # only the ideas that have a deadline
        self.popups = []

    def load_if_changed(self):
        """Read the ideas file again only if it changed (comparing its time and size is very cheap)."""
        try:
            info = IDEAS_FILE.stat()
        except FileNotFoundError:
            self.ideas = []
            return
        stamp = (info.st_mtime_ns, info.st_size)
        if stamp == self.stamp:
            return
        self.stamp = stamp
        ideas = []
        with open(IDEAS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("due") and "parent" not in record and "link" not in record:
                    ideas.append(record)
        self.ideas = ideas

    def check(self):
        try:
            self.load_if_changed()
            for idea, minutes in reminders.due_reminders(self.ideas, IDEAS_FILE):
                reminders.mark_sent(IDEAS_FILE, idea, minutes)
                self.show(idea, minutes)
        finally:
            self.root.after(CHECK_REMINDERS_MS, self.check)

    def show(self, idea, minutes):
        """A small pop-up in the bottom-right corner, in the app's colours."""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=WINDOW_BG)
        width, height = 360, 128
        stack = len([p for p in self.popups if p.winfo_exists()])
        x = win.winfo_screenwidth() - width - 24
        y = win.winfo_screenheight() - height - 72 - stack * (height + 12)
        win.geometry(f"{width}x{height}+{x}+{y}")
        title = idea.get("title") or idea.get("text", "").partition("\n")[0] or "(no title)"
        when = reminders.LABELS.get(minutes, "")
        tk.Label(win, text="⏰  Reminder" + (f"  ·  {when}" if minutes else "  ·  due now"), bg=WINDOW_BG,
                 fg=HINT, font=SMALL_FONT, anchor="w", padx=16).pack(fill="x", pady=(12, 0))
        tk.Label(win, text=title[:42], bg=WINDOW_BG, fg=TEXT, font=(_SEMIBOLD, 12), anchor="w",
                 padx=16).pack(fill="x")
        tk.Label(win, text=reminders.describe_due(idea["due"]), bg=WINDOW_BG, fg=HINT, font=SMALL_FONT,
                 anchor="w", padx=16).pack(fill="x")
        buttons = tk.Frame(win, bg=WINDOW_BG)
        buttons.pack(fill="x", padx=16, pady=(8, 0))
        for label, action, colour in (("Open", lambda: self.open(idea, win), _THEME["accent"]),
                                      ("Dismiss", win.destroy, HINT)):
            b = tk.Label(buttons, text=label, bg=WINDOW_BG, fg=colour, font=SMALL_FONT, cursor="hand2")
            b.pack(side="left", padx=(0, 16))
            b.bind("<Button-1>", lambda e, a=action: a())
        win.update_idletasks()
        round_corners(win)
        win.after(10 * 60_000, lambda: win.winfo_exists() and win.destroy())    # gone after 10 minutes
        self.popups.append(win)

    def open(self, idea, win):
        """Show the idea in the galaxy app (a small request file tells the app which one)."""
        (IDEAS_FOLDER / "open_request.json").write_text(json.dumps({"idea": idea["created"]}), encoding="utf-8")
        open_map()
        win.destroy()


def main():
    box = CaptureBox()
    box.reminders = Reminders(box.root)
    box.root.after(5_000, box.reminders.check)       # first check 5 s after starting

    def run_listener():
        # This function runs in the second thread.
        # event_generate sends a message to the window, which lives in the
        # main thread. It's the safe way for a thread to talk to Tkinter.
        try:
            hotkey.listen(
                on_capture=lambda: box.root.event_generate("<<Capture>>", when="tail"),
                on_map=open_map,  # this one doesn't touch Tkinter, so it can run here
                capture_key=settings.hotkey_spec(SETTINGS["capture_hotkey"], "ctrl_alt_i")[1:],
                map_key=settings.hotkey_spec(SETTINGS["map_hotkey"], "ctrl_alt_m")[1:],
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
