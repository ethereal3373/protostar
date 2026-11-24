"""
ideas_store.py — reading and changing the ideas file (used by the main app).

The file: ideas/ideas.jsonl — one JSON record per line. Three kinds:

  idea:  {"created": "2026-11-24T10:00:00", "title": "...", "text": "...", "slot": 7}
  note:  {"created": "...", "parent": "<the idea's created time>", "text": "..."}
  link:  {"created": "...", "link": ["<idea A's created time>", "<idea B's created time>"]}

An idea's "created" time works as its name tag (an "ID"): notes and links
point to their ideas with it.

"slot" = the idea's place in the galaxy
---------------------------------------
Stars are placed by number: idea 0 near the core, idea 500 further out.
If we simply used "the n-th idea in the file", deleting one idea would shift
every later star. So each idea keeps its own number, its "slot", forever.
Ideas saved by the capture note have no slot yet: they get the next free
number when the file is read, and it's written down the next time the app
saves the file.

Saving safely
-------------
Adding a new idea (the capture note) just adds a line at the end. Editing
or deleting means rewriting the whole file. To never end up with a
half-written file (for example if the PC turns off at the wrong moment),
we write a new temporary file first and then swap it in with one quick
operation (os.replace).
"""

import json
import os
from datetime import datetime


def now():
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = path
        self.load()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def load(self):
        self.ideas, self.notes, self.links = [], {}, []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # a damaged line: skip it rather than crash
                    if "parent" in record:
                        self.notes.setdefault(record["parent"], []).append(record)
                    elif "link" in record:
                        self.links.append(record)
                    else:
                        self.ideas.append(record)
        # Give every idea without a slot the next free number.
        next_slot = max((i["slot"] for i in self.ideas if "slot" in i), default=-1) + 1
        for idea in self.ideas:
            if "slot" not in idea:
                idea["slot"] = next_slot
                next_slot += 1
        # Forget links whose ideas no longer exist.
        names = {i["created"] for i in self.ideas}
        self.links = [l for l in self.links if l["link"][0] in names and l["link"][1] in names]

    def notes_of(self, idea):
        return self.notes.get(idea["created"], [])

    def linked_to(self, idea):
        """The ideas linked with `idea`."""
        me = idea["created"]
        others = {l["link"][1] if l["link"][0] == me else l["link"][0]
                  for l in self.links if me in l["link"]}
        return [i for i in self.ideas if i["created"] in others]

    def activity(self, idea):
        """
        The last time something happened to this idea: created, opened,
        edited, or a note added. Used to make busy ideas shine brighter.
        """
        times = [idea["created"], idea.get("opened", ""), idea.get("edited", "")]
        times += [n["created"] for n in self.notes_of(idea)]
        return max(t[:19] for t in times if t)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def save(self):
        """Rewrite the whole file safely (see "Saving safely" above)."""
        self.path.parent.mkdir(exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as f:
            for idea in self.ideas:
                f.write(json.dumps(idea, ensure_ascii=False) + "\n")
            for notes in self.notes.values():
                for note in notes:
                    f.write(json.dumps(note, ensure_ascii=False) + "\n")
            for link in self.links:
                f.write(json.dumps(link, ensure_ascii=False) + "\n")
        os.replace(temporary, self.path)       # the quick swap

    def change(self, action):
        """
        Re-read the file, make a change, save. Re-reading first means we
        never throw away an idea the capture note added a moment ago.
        """
        self.load()
        action()
        self.save()

    # --- Ideas ---
    def find(self, created):
        return next((i for i in self.ideas if i["created"] == created), None)

    def edit_idea(self, created, title, text):
        def action():
            idea = self.find(created)
            if idea:
                idea["title"], idea["text"], idea["edited"] = title, text, now()
        self.change(action)

    def delete_idea(self, created):
        """Delete an idea together with its notes and links."""
        def action():
            self.ideas = [i for i in self.ideas if i["created"] != created]
            self.notes.pop(created, None)
            self.links = [l for l in self.links if created not in l["link"]]
        self.change(action)

    def mark_opened(self, created):
        def action():
            idea = self.find(created)
            if idea:
                idea["opened"] = now()
        self.change(action)

    # --- Notes ---
    def add_note(self, parent, text):
        def action():
            # Notes get the time down to the microsecond, so two notes added
            # in the same second still have different name tags.
            self.notes.setdefault(parent, []).append(
                {"created": datetime.now().isoformat(), "parent": parent, "text": text})
        self.change(action)

    def edit_note(self, parent, created, text):
        def action():
            for note in self.notes.get(parent, []):
                if note["created"] == created:
                    note["text"], note["edited"] = text, now()
        self.change(action)

    def delete_note(self, parent, created):
        def action():
            self.notes[parent] = [n for n in self.notes.get(parent, []) if n["created"] != created]
        self.change(action)

    # --- Links (constellations) ---
    def add_link(self, a, b):
        def action():
            if a != b and not any(set(l["link"]) == {a, b} for l in self.links):
                self.links.append({"created": now(), "link": [a, b]})
        self.change(action)

    def remove_link(self, a, b):
        def action():
            self.links = [l for l in self.links if set(l["link"]) != {a, b}]
        self.change(action)
