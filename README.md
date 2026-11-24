# Protostar

Protostar is a lightweight desktop app for catching ideas the moment they appear. Press a global keyboard shortcut and a small floating box pops up: type the idea, hit Enter, and it's saved without breaking your flow. Your ideas then live on a galaxy-style map, where each idea is a star you can explore, group, and connect. It is built to stay almost invisible while running in the background (near 0% CPU, low memory), and it has no AI features — just your own thoughts, kept fast and private on your machine.

## How to use (Windows, Python 3)

First time only, install the libraries the main app uses (Pillow for images, numpy for the 3D maths):

```
python -m pip install -r requirements.txt
```

| Command | What it does |
|---|---|
| `python protostar.py` | Run Protostar in this terminal (good for testing) |
| `python startup.py install` | Start Protostar now, and every time you log in, with no terminal window |
| `python startup.py remove` | Stop starting it at login |
| `python map.py` | Open the main app: your ideas as a 3D galaxy |
| `python map.py demo` | Open a demo galaxy with 20 sample ideas (kept separate from your real ideas) |
| `python demo.py --reset` | Throw the demo away and make a fresh one |

- **Ctrl+Alt+I**: open the capture note. The first line is the idea's title. **Enter** saves the idea, **Shift+Enter** adds a new line, **Esc** closes it without saving, but your draft is kept for next time. Click **"New idea ▾"** at the top to add a note to an existing idea instead.
- **Ctrl+Alt+M**: open the main app.
- **Ctrl+Alt+Q**: quit Protostar.

### The main app
- **Left**: all your ideas in folders by month. Click a folder or an idea to open/close it; clicking an idea also flies to its star. An open idea shows its text, its **notes** (✎ edit, × delete), the ideas it's **linked** to, and **Edit · Link to… · Delete**. Type in "Add a note…" and press Enter to add a note.
- **Top**: idea and link counts, **Overview** (see everything), **Timeline** (a slider and ▶ Play to watch your galaxy grow from your first idea to today).
- **Middle**: the galaxy. Every idea is a star and brings its own cloud of light, so the galaxy builds itself as you add ideas. Notes are tiny stars next to their idea. **Linked ideas are joined by faint lines: constellations.** Ideas you've touched recently (opened, edited, added notes) shine brighter; forgotten ones slowly dim.
- **Right**: search your ideas by any words in the title, text or notes.

To link two ideas: open one, click **Link to…**, then click another star (or another idea in the sidebar). Esc cancels.

#### Moving around the galaxy (like Roblox Studio)
| Input | Does |
|---|---|
| Mouse wheel | Fly towards (or away from) whatever the mouse points at |
| Left-drag | Circle around what you're looking at |
| Right-drag | Look around (turn your head) |
| Middle-drag | Slide sideways |
| W A S D | Fly forward / left / back / right (click the galaxy first) |
| E / Q | Up / down |
| Shift | Hold to move faster |
| F | Fly to the selected star |
| Home | Back to the overview |
| Hover / click a star | See its title / open it in the sidebar |

Ideas are saved in `ideas/ideas.jsonl`, on your computer only.
