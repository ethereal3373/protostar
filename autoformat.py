"""
autoformat.py — Word-style automatic formatting for Protostar's text boxes.

  - Type "-" and a space at the start of a line: it becomes a round bullet
    "• ", and if the line is long, the wrapped part lines up under the text
    (not under the bullet).
  - Start a new line after a bullet line: the new line gets a bullet too.
    Start a new line on an EMPTY bullet line: the list ends.
    Backspace right after a bullet: the bullet goes away.
  - The first letter of a line, and the first letter after ". ", "! " or
    "? ", becomes a capital letter.

Use it with attach(text_widget, newline_key) on any tk.Text.
"""

import tkinter.font as tkfont

BULLET = "• "
SENTENCE_ENDS = (". ", "! ", "? ")


def attach(text, newline_key="<Shift-Return>"):
    """
    Switch on automatic formatting for a tk.Text widget. `newline_key` is
    the key that makes a new line in this box (Shift+Enter in the capture
    note when Enter saves; plain Enter when Ctrl+Enter saves).
    """
    font = tkfont.Font(font=text.cget("font"))
    # Wrapped lines of a bullet start where the text after "• " starts.
    text.tag_configure("bullet", lmargin1=0, lmargin2=font.measure(BULLET))

    def line_before_cursor():
        return text.get("insert linestart", "insert")

    def on_space(event):
        if line_before_cursor() == "-":                  # "-" + space at the start of a line
            text.delete("insert linestart", "insert")
            text.insert("insert", BULLET)
            retag()
            return "break"
        return None

    def on_letter(event):
        ch = event.char
        if not (len(ch) == 1 and ch.isalpha() and ch.islower()):
            return None
        before = line_before_cursor()
        start_of_line = before.strip() == "" or before == BULLET
        after_sentence = before.endswith(SENTENCE_ENDS)
        if start_of_line or after_sentence:
            if text.tag_ranges("sel"):
                text.delete("sel.first", "sel.last")     # typing over a selection
            text.insert("insert", ch.upper())
            return "break"
        return None

    def on_newline(event):
        line = text.get("insert linestart", "insert lineend")
        if line.startswith(BULLET):
            if line.strip() == BULLET.strip():           # empty bullet: end the list
                text.delete("insert linestart", "insert lineend")
            else:
                text.insert("insert", "\n" + BULLET)     # continue the list
            retag()
            text.see("insert")
            return "break"
        return None                                      # normal new line

    def on_backspace(event):
        if line_before_cursor() == BULLET and not text.tag_ranges("sel"):
            text.delete("insert linestart", "insert")    # remove the bullet only
            retag()
            return "break"
        return None

    def retag(event=None):
        """Give every bullet line the "bullet" style (so wrapped lines line up)."""
        text.tag_remove("bullet", "1.0", "end")
        last = int(text.index("end-1c").split(".")[0])
        for n in range(1, last + 1):
            if text.get(f"{n}.0", f"{n}.2") == BULLET:
                text.tag_add("bullet", f"{n}.0", f"{n}.end")

    text.bind("<space>", on_space, add="+")
    text.bind("<KeyPress>", on_letter, add="+")
    text.bind(newline_key, on_newline, add="+")
    text.bind("<BackSpace>", on_backspace, add="+")
    text.bind("<KeyRelease>", retag, add="+")
    retag()
    return retag
