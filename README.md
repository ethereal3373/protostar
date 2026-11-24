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

- **Ctrl+Alt+I**: open the capture note. The first line is the idea's title. **Enter** saves the idea, **Shift+Enter** adds a new line, **Esc** closes it (your draft is kept).
- **Ctrl+Alt+M**: open the main app.
- **Ctrl+Alt+Q**: quit Protostar.

### The main app
- **Left**: all your ideas in folders by month. Click a folder or an idea to open/close it; clicking an idea also flies to its star.
- **Middle**: the galaxy. Every idea is a star and brings its own cloud of light, so the galaxy builds itself as you add ideas. Left-drag to turn around it, right-drag to slide, mouse wheel to zoom, hover a star for its title, click it to open the idea.
- **Right**: search your ideas by any words in the title or text.

Ideas are saved in `ideas/ideas.jsonl`, on your computer only.
