"""
ideas_store.py — reading and changing the ideas file (used by the main app).

The file: ideas/ideas.jsonl — one JSON record per line. Three kinds:

  idea:  {"created": "2026-11-24T10:00:00", "title": "...", "text": "...", "slot": 7}
  note:  {"created": "...", "parent": "<the idea's created time>", "text": "..."}
  link:  {"created": "...", "link": ["<idea A's created time>", "<idea B's created time>"]}

Ideas can also have: "stage" ("spark", "growing" or "done"), "opened" and
"edited" times, and "deleted" (the time it was moved to the Trash).

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

The Trash
---------
Deleting an idea only marks it "deleted": it disappears from the galaxy,
but waits in the Trash for 30 days (with its notes and links), where it can
be restored. After 30 days it's removed for good.

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
import re
import shutil
from datetime import datetime, timedelta

TRASH_DAYS = 30     # how long deleted ideas wait in the Trash
STAGES = ("spark", "growing", "done")
# A "regular expression": a pattern for finding text. This one means
# "a # followed by one or more letters, digits or _" — a #tag.
TAG = re.compile(r"#(\w+)")


def now():
    return datetime.now().isoformat(timespec="seconds")


def title_of(idea):
    """An idea's title (older ideas without a title use their first line)."""
    if "title" in idea:
        return idea["title"]
    return idea.get("text", "").partition("\n")[0]


def text_of(idea):
    if "title" in idea:
        return idea.get("text", "")
    return idea.get("text", "").partition("\n")[2]


class Store:
    def __init__(self, path):
        self.path = path
        self.load()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def load(self):
        self.ideas, self.trash, self.notes, self.all_links = [], [], {}, []
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
                        self.all_links.append(record)
                    elif "deleted" in record:
                        self.trash.append(record)      # in the Trash: hidden, not gone
                    else:
                        self.ideas.append(record)
        # The Trash empties itself: ideas deleted more than 30 days ago are
        # removed for good (with their notes and links) the next time we save.
        limit = (datetime.now() - timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds")
        for idea in [i for i in self.trash if i["deleted"] < limit]:
            self.forget(idea["created"])
        # Give every idea without a slot the next free number (the Trash too,
        # so a restored idea returns to exactly the same place).
        everyone = self.ideas + self.trash
        next_slot = max((i["slot"] for i in everyone if "slot" in i), default=-1) + 1
        for idea in everyone:
            if "slot" not in idea:
                idea["slot"] = next_slot
                next_slot += 1

    @property
    def links(self):
        """Links between two ideas that are both alive (not in the Trash)."""
        alive = {i["created"] for i in self.ideas}
        return [l for l in self.all_links if l["link"][0] in alive and l["link"][1] in alive]

    def find(self, created):
        return next((i for i in self.ideas if i["created"] == created), None)

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
            for idea in self.ideas + self.trash:
                f.write(json.dumps(idea, ensure_ascii=False) + "\n")
            for notes in self.notes.values():
                for note in notes:
                    f.write(json.dumps(note, ensure_ascii=False) + "\n")
            for link in self.all_links:
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

    def forget(self, created):
        """Remove an idea, its notes and its links completely (no Trash)."""
        self.ideas = [i for i in self.ideas if i["created"] != created]
        self.trash = [i for i in self.trash if i["created"] != created]
        self.notes.pop(created, None)
        self.all_links = [l for l in self.all_links if created not in l["link"]]

    # --- Ideas ---
    def edit_idea(self, created, title, text):
        def action():
            idea = self.find(created)
            if idea:
                idea["title"], idea["text"], idea["edited"] = title, text, now()
        self.change(action)

    def set_stage(self, created, stage):
        """An idea's life stage: "spark" (new), "growing" (working on it), "done"."""
        def action():
            idea = self.find(created)
            if idea:
                idea["stage"], idea["edited"] = stage, now()
        self.change(action)

    def toggle_pin(self, created):
        """Pinned ideas stay at the top of the list and never fade."""
        def action():
            idea = self.find(created)
            if idea:
                if idea.get("pinned"):
                    del idea["pinned"]
                else:
                    idea["pinned"] = True
        self.change(action)

    def tags(self):
        """
        All #tags written in titles, texts and notes, with how many ideas use
        each one, most used first. A tag is a # followed by letters or numbers.
        """
        counts = {}
        for idea in self.ideas:
            words = " ".join([title_of(idea), text_of(idea)] + [n["text"] for n in self.notes_of(idea)])
            for tag in set(TAG.findall(words.lower())):
                counts[tag] = counts.get(tag, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def stats(self):
        """Numbers for the Stats panel."""
        today = datetime.now().date()
        days = {datetime.fromisoformat(i["created"]).date() for i in self.ideas}
        streak, day = 0, today
        if day not in days:                     # no idea yet today: the streak can still continue
            day -= timedelta(days=1)
        while day in days:
            streak += 1
            day -= timedelta(days=1)
        week_start = today - timedelta(days=today.weekday())
        linked = {}
        for l in self.links:
            for name in l["link"]:
                linked[name] = linked.get(name, 0) + 1
        hub = max(linked, key=linked.get) if linked else None
        return {
            "ideas": len(self.ideas),
            "this week": sum(1 for d in (datetime.fromisoformat(i["created"]).date() for i in self.ideas)
                             if d >= week_start),
            "this month": sum(1 for i in self.ideas if i["created"][:7] == f"{today:%Y-%m}"),
            "streak": streak,
            "growing": sum(1 for i in self.ideas if i.get("stage") == "growing"),
            "done": sum(1 for i in self.ideas if i.get("stage") == "done"),
            "notes": sum(len(self.notes_of(i)) for i in self.ideas),
            "links": len(self.links),
            "hub": (title_of(self.find(hub)), linked[hub]) if hub else None,
        }

    def mark_opened(self, created):
        def action():
            idea = self.find(created)
            if idea:
                idea["opened"] = now()
        self.change(action)

    def delete_idea(self, created):
        """Move an idea to the Trash (its notes and links wait there with it)."""
        def action():
            idea = self.find(created)
            if idea:
                idea["deleted"] = now()
                self.ideas.remove(idea)
                self.trash.append(idea)
        self.change(action)

    def restore_idea(self, created):
        """Take an idea out of the Trash: it comes back with its notes and links."""
        def action():
            for idea in self.trash:
                if idea["created"] == created:
                    del idea["deleted"]
                    self.trash.remove(idea)
                    self.ideas.append(idea)
                    break
        self.change(action)

    def delete_forever(self, created):
        self.change(lambda: self.forget(created))

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
            if a != b and not any(set(l["link"]) == {a, b} for l in self.all_links):
                self.all_links.append({"created": now(), "link": [a, b]})
        self.change(action)

    def remove_link(self, a, b):
        def action():
            self.all_links = [l for l in self.all_links if set(l["link"]) != {a, b}]
        self.change(action)

    # ------------------------------------------------------------------
    # Backups and export
    # ------------------------------------------------------------------
    def daily_backup(self, keep=14):
        """
        Once a day, copy the ideas file into ideas/backups/. Only the newest
        `keep` copies are kept. If something ever goes wrong with the file,
        yesterday's ideas are still safe.
        """
        if not self.path.exists():
            return None
        folder = self.path.parent / "backups"
        folder.mkdir(exist_ok=True)
        today = folder / f"{self.path.stem}-{datetime.now():%Y-%m-%d}.jsonl"
        if not today.exists():
            shutil.copy2(self.path, today)
        copies = sorted(folder.glob(f"{self.path.stem}-*.jsonl"))
        for old in copies[:-keep]:
            old.unlink()
        return today

    def export_markdown(self):
        """
        Write all ideas into one readable Markdown file (a simple text format:
        # for headings, - for lists). Easy to read, print, or open anywhere.
        """
        lines = ["# Protostar — my ideas", "", f"Exported {datetime.now():%d %B %Y, %H:%M}.", ""]
        month = None
        for idea in sorted(self.ideas, key=lambda i: i["created"], reverse=True):
            created = datetime.fromisoformat(idea["created"])
            if f"{created:%B %Y}" != month:
                month = f"{created:%B %Y}"
                lines += [f"## {month}", ""]
            lines.append(f"### {title_of(idea) or '(no title)'}  ·  {idea.get('stage', 'spark')}"
                         f"  ·  {created:%d %b %Y}")
            if text_of(idea):
                lines += ["", text_of(idea)]
            notes = self.notes_of(idea)
            if notes:
                lines += [""] + [f"- {n['text']}" for n in notes]
            linked = self.linked_to(idea)
            if linked:
                lines += ["", "Linked: " + ", ".join(title_of(o) for o in linked)]
            lines.append("")
        target = self.path.parent / f"{self.path.stem} export {datetime.now():%Y-%m-%d}.md"
        target.write_text("\n".join(lines), encoding="utf-8")
        return target
