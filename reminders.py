"""
reminders.py — deadlines and reminders for ideas.

An idea can have:
    "due":    "2026-11-30T18:00"         when it's due
    "remind": [1440, 240]                 when to remind you: minutes before
                                          (0 = at the time, 60 = 1 hour before,
                                           1440 = 1 day before, ...)

The background part (protostar.py) calls due_reminders() once a minute and
shows a small pop-up for each one. Which reminders were already shown is
written in ideas/reminders_sent.json, so each one appears only once (even
if the PC was off at the time: it shows when Protostar starts, if it's
less than a day late).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

# The choices offered in the app (minutes before the deadline, label).
CHOICES = [(0, "At the time"), (15, "15 min before"), (30, "30 min before"), (60, "1 h before"),
           (120, "2 h before"), (240, "4 h before"), (1440, "1 day before"), (2880, "2 days before"),
           (10080, "1 week before")]
LABELS = dict(CHOICES)


def parse_date(text, today=None):
    """
    Understand a date typed in a friendly way: "2026-11-30", "30/11",
    "30/11/2026", "30.11", "30-11-2026". Returns a date, or None.
    """
    today = today or datetime.now().date()
    text = text.strip().replace(".", "/").replace("-", "/")
    parts = [p for p in text.split("/") if p]
    try:
        if len(parts) == 3 and len(parts[0]) == 4:            # 2026/11/30
            return datetime(int(parts[0]), int(parts[1]), int(parts[2])).date()
        if len(parts) == 3:                                    # 30/11/2026
            year = int(parts[2]) + (2000 if len(parts[2]) == 2 else 0)
            return datetime(year, int(parts[1]), int(parts[0])).date()
        if len(parts) == 2:                                    # 30/11 -> this year (or next, if passed)
            day = datetime(today.year, int(parts[1]), int(parts[0])).date()
            return day if day >= today else day.replace(year=today.year + 1)
    except ValueError:
        return None
    return None


def parse_time(text):
    """ "18:00", "18.30", "9" -> (hour, minute), or None."""
    text = text.strip().replace(".", ":")
    try:
        if ":" in text:
            h, m = text.split(":")[:2]
            h, m = int(h), int(m)
        else:
            h, m = int(text), 0
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return None


def describe_due(due_iso, now=None):
    """ "Sun 30 Nov, 18:00 · in 3 days"  (or "· 2 h late")."""
    now = now or datetime.now()
    due = datetime.fromisoformat(due_iso)
    left = due - now
    if left.total_seconds() < 0:
        late = -left
        when = f"{late.days} d late" if late.days else f"{int(late.total_seconds() // 3600)} h late"
    elif left.days >= 1:
        when = f"in {left.days} day{'s' if left.days != 1 else ''}"
    elif left.total_seconds() >= 3600:
        when = f"in {int(left.total_seconds() // 3600)} h"
    else:
        when = f"in {max(1, int(left.total_seconds() // 60))} min"
    return f"{due:%a %d %b, %H:%M}  ·  {when}"


def _sent_file(ideas_file):
    return Path(ideas_file).parent / "reminders_sent.json"


def due_reminders(ideas, ideas_file, now=None):
    """
    The reminders that should pop up now: a list of (idea, minutes_before).
    `ideas` are the idea records (dicts). Ideas that are done or in the
    Trash never remind you.
    """
    now = now or datetime.now()
    try:
        sent = set(json.loads(_sent_file(ideas_file).read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        sent = set()
    found = []
    for idea in ideas:
        if not idea.get("due") or idea.get("deleted") or idea.get("stage") == "done":
            continue
        due = datetime.fromisoformat(idea["due"])
        for minutes in idea.get("remind", []):
            moment = due - timedelta(minutes=minutes)
            key = f"{idea['created']}|{idea['due']}|{minutes}"
            if moment <= now < moment + timedelta(days=1) and key not in sent:
                found.append((idea, minutes))
    return found


def mark_sent(ideas_file, idea, minutes):
    """Remember that this reminder was shown, so it doesn't appear again."""
    path = _sent_file(ideas_file)
    try:
        sent = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        sent = []
    sent.append(f"{idea['created']}|{idea['due']}|{minutes}")
    path.write_text(json.dumps(sent[-500:]), encoding="utf-8")    # keep it small
