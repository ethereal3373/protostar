"""
demo.py — a demo galaxy with 20 sample ideas, to see how the app looks and
performs with more than a couple of ideas.

    python map.py demo          open the demo galaxy
    python demo.py --reset      throw the demo away and make a fresh one

The demo lives in its own file (ideas/demo.jsonl), so your real ideas are
never mixed with it. Like your real ideas, it's never uploaded to GitHub
(the ideas/ folder is in .gitignore).
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEMO_FILE = Path(__file__).parent / "ideas" / "demo.jsonl"

# (title, text, [notes])
SAMPLES = [
    ("Trip to Iceland", "See the northern lights in winter. Rent a car and drive the ring road. #travel #photo",
     ["Best months: February-March", "Check hot springs near Reykjavik"]),
    ("Recipe app", "An app that suggests recipes from what's left in the fridge. #coding #food",
     ["Could scan receipts to know what I bought"]),
    ("Learn to draw stars", "Practise drawing realistic stars and nebulae digitally. #art #space", []),
    ("Vertical garden on the balcony", "Herbs and strawberries in hanging pots.",
     ["Basil, mint, rosemary", "Needs a drip watering system"]),
    ("Short story set on Mars", "A botanist trying to grow the first tree on Mars. #writing #space", []),
    ("Memory techniques", "Read about the memory palace method and try it for exams.",
     ["Start with the periodic table"]),
    ("Study playlist", "Instrumental music only, slow tempo.", []),
    ("Birthday present for mum", "A photo book of our holidays.", ["Ask dad for old photos"]),
    ("Protostar: link similar ideas", "Constellations between related stars.", []),
    ("Night photography", "Photograph the Milky Way away from city lights. #photo #space",
     ["Need a tripod", "Try a 20-second exposure"]),
    ("Learn Italian cooking", "Fresh pasta from scratch. #food", []),
    ("Morning routine", "Wake up at 7, stretch, no phone for the first hour. #health", []),
    ("Build a small game", "A tiny space exploration game in Python. #coding #space", ["Use pygame?"]),
    ("Volunteer at the library", "Help with the reading club for kids.", []),
    ("Run a 10k", "Train three times a week for two months. #health", ["Week 1: 3 x 3 km"]),
    ("Telescope", "Save up for a beginner telescope. #space", []),
    ("Write a journal", "Five lines every evening.", []),
    ("Second-hand bike", "Fix up an old bike for the city.", []),
    ("Language exchange", "Find someone to practise English with.", []),
    ("Clean up old photos", "Sort and back up all phone photos.", []),
]

# Pairs of ideas (by number in SAMPLES) that belong together: constellations.
LINKS = [(0, 9), (9, 15), (2, 15), (2, 9), (1, 10), (5, 6), (14, 11), (12, 8), (4, 2)]


def make_demo_file(reset=False):
    """Create the demo file if it doesn't exist yet (or if reset=True). Returns its path."""
    if DEMO_FILE.exists() and not reset:
        return DEMO_FILE
    rng = random.Random(4)
    start = datetime.now() - timedelta(days=90)
    records = []
    names = []
    for i, (title, text, notes) in enumerate(SAMPLES):
        created = start + timedelta(days=i * 4.5, hours=rng.randint(8, 22), minutes=rng.randint(0, 59))
        name = created.isoformat(timespec="seconds")
        names.append(name)
        idea = {"created": name, "title": title, "text": text, "slot": i}
        # Some ideas were opened recently (they'll shine brighter), others not.
        if i in (9, 2):
            idea["stage"] = "growing"
        if i in (5, 14):
            idea["stage"] = "done"
        if i == 0:
            idea["pinned"] = True
        if i % 3 == 0:
            idea["opened"] = (datetime.now() - timedelta(days=rng.randint(0, 3))).isoformat(timespec="seconds")
        records.append(idea)
        for j, note in enumerate(notes):
            records.append({"created": (created + timedelta(days=j + 1)).isoformat(),
                            "parent": name, "text": note})
    for a, b in LINKS:
        records.append({"created": names[max(a, b)], "link": [names[a], names[b]]})
    DEMO_FILE.parent.mkdir(exist_ok=True)
    with open(DEMO_FILE, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return DEMO_FILE


if __name__ == "__main__":
    path = make_demo_file(reset="--reset" in sys.argv)
    print(f"Demo galaxy ready: {path}\nOpen it with:  python map.py demo")
