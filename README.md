# Protostar

Protostar is a lightweight desktop app for catching ideas the moment they appear. Press a global keyboard shortcut and a small floating box pops up: type the idea, hit Enter, and it's saved without breaking your flow. Your ideas then live on a galaxy-style map, where each idea is a star you can explore, group, and connect. It is built to stay almost invisible while running in the background (near 0% CPU, low memory), and it has no AI features — just your own thoughts, kept fast and private on your machine.

## How to use (Windows, Python 3)

| Command | What it does |
|---|---|
| `python protostar.py` | Run Protostar in this terminal (good for testing) |
| `python startup.py install` | Start Protostar now, and every time you log in, with no terminal window |
| `python startup.py remove` | Stop starting it at login |
| `python map.py` | Open the galaxy map of your ideas (hover a star to peek, click to read, Esc to close) |

- **Ctrl+Alt+I**: open the capture box. **Enter** saves the idea, **Esc** closes the box.
- **Ctrl+Alt+Q**: quit Protostar.

Ideas are saved in `ideas/ideas.jsonl`, on your computer only.
