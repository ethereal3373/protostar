# Protostar through a new user's eyes

A step back from being the creator: what would someone who just downloaded
Protostar find confusing, inefficient, or just not to their taste?

Status: ✅ = done (in the app now, check it and keep or remove it) ·
🔜 = proposed (not built yet)

The rule of thumb used here: **one good default for everybody, and a choice
in Settings where people genuinely differ** (taste, keyboard habits, PC
power). Not a choice for everything — too many options is its own problem.

---

## 1. Getting it and starting it

| | What a new user would hit | What to do |
|---|---|---|
| 🔜 | It needs Python, Git and typing commands. Most people stop here. | A real installer (`Protostar-Setup.exe`), see [RELEASE.md](RELEASE.md). |
| 🔜 | Windows shows "Windows protected your PC" for unknown apps. | Code signing, or explain the "More info → Run anyway" step on the download page. |
| 🔜 | Nothing explains the app the first time. | A first-run welcome: 3 short cards (catch with the shortcut → see the galaxy → link ideas), plus an option to open the demo galaxy. |
| 🔜 | With 0 ideas the galaxy is just black. | An empty-state message in the middle: "Your galaxy starts with one idea — press Ctrl+Alt+I". |
| 🔜 | No icon of its own (it shows the Python feather). | A Protostar icon for the windows, the taskbar and the installer. |
| 🔜 | No way to see Protostar is running in the background. | Optional tray icon (New idea / Open galaxy / Settings / Quit). Off by default to keep it light. |

## 2. Your data: safety and trust

| | Concern | What to do |
|---|---|---|
| ✅ | "What if I delete something by mistake?" | Trash (30 days) and daily backups (14 days). |
| ✅ | "Can I get my ideas out?" | Export to Markdown. |
| 🔜 | Ideas live inside the program's folder. An installed app (in *Program Files*) can't write there, and uninstalling would delete them. | Move ideas and settings to `%APPDATA%\Protostar` (with automatic migration of existing ideas). **Needed before a public release.** |
| 🔜 | "Can I sync between my two PCs?" | Settings → choose the ideas folder (e.g. inside OneDrive or Dropbox). |
| 🔜 | "Is my data sent anywhere?" | Say clearly on the website and in the app: nothing leaves your PC; the only network use is the optional AI connection, which *you* set up. |
| 🔜 | Import from other apps | Import from a Markdown folder / Obsidian, plain text (one idea per line), Google Keep export. |
| 🔜 | Undo | Ctrl+Z for the last action (edit, delete, link), not only the Trash. |

## 3. The capture note

| | | |
|---|---|---|
| ✅ | Some people expect Enter = new line. | Settings → Saving: "Enter saves" or "Ctrl+Enter saves". |
| ✅ | The shortcut might clash with another app. | Settings → choose from 4 shortcuts. |
| 🔜 | Pick any shortcut, not only from a list. | A "press your shortcut" recorder. |
| 🔜 | Add #tags or a stage while capturing. | Already possible by typing #tags; a stage picker could be added to the ▾ menu. |
| 🔜 | Capture from the clipboard | A second shortcut that saves the copied text as an idea in one keypress. |
| 🔜 | Multiple screens | Open the note on the screen where the mouse is. |
| 🔜 | Voice | Dictation already works through Windows (Win+H) — mention it in the tips. |

## 4. The main app

| | | |
|---|---|---|
| ✅ | Taste in colours varies a lot. | Settings → Theme (Midnight, Graphite, Warm, Daylight) and Accent (blue, teal, violet, amber). |
| ✅ | Some people prefer the standard Windows font. | Settings → Font: Inter or Segoe UI. |
| ✅ | Moving animations can bother some people (motion sensitivity). | Settings → Animations: on/off. |
| 🔜 | Sorting the list | Newest / oldest / recently active / A–Z, and grouping by month, by tag, or by stage. |
| 🔜 | Resizable panels | Drag the edges of the sidebar and the search panel; hide either one (more galaxy). |
| 🔜 | Full keyboard use | Arrow keys through the list, Enter to open, Delete to trash, `?` to show all shortcuts. |
| 🔜 | Multi-select | Select several ideas to tag, link, move to Trash or change stage at once. |
| 🔜 | Rich text in ideas | Simple Markdown (bold, lists, links) shown nicely in the sidebar. |
| 🔜 | Text size | Settings → Text size (small / normal / large) for readability. |
| 🔜 | Languages | Translations of the interface (English first; Italian would be easy to add next). |

## 5. The galaxy

| | | |
|---|---|---|
| ✅ | Weaker PCs | Settings → Detail: Low / Normal / High. |
| ✅ | "I want colours to mean something" | Settings → Star colours: Natural, or by #tag. |
| 🔜 | People who don't use a mouse wheel (laptop touchpads) | Touchpad pinch to zoom, two-finger drag to move; on-screen + / − buttons. |
| 🔜 | "Where am I?" when lost in 3D | A small compass / mini-map in a corner, and "Overview" already brings you back. |
| 🔜 | Labels | Option to always show the titles of nearby stars, not only on hover. |
| 🔜 | Galaxy shape | Choice of shapes (spiral, barred spiral, elliptical) — purely for fun. |
| 🔜 | No graphics card / old drivers | A fallback that draws with the processor (the old renderer still exists in `galaxy3d.py`). |

## 6. Accessibility

| | | |
|---|---|---|
| 🔜 | Colour blindness | Stage and tag colours always come with a symbol (✦ ★ ●), never colour alone — mostly done; check every place. |
| 🔜 | Screen readers | Hard with Tkinter; at least make every action reachable from the keyboard. |
| 🔜 | Contrast | A high-contrast theme. |

## 7. The AI connection (MCP)

| | | |
|---|---|---|
| ✅ | Connect Claude Code | Done for this PC, everywhere. |
| 🔜 | Read-only option | Settings → "AI can read only / read and add notes", for people who don't want an AI changing anything. |
| 🔜 | One-click setup | A button in Settings that sets up Claude Code / Claude Desktop for you. |

## 8. Other platforms

| | | |
|---|---|---|
| 🔜 | Mac and Linux | The shortcuts, fonts and window corners use Windows-only features; each needs a Mac/Linux version. Big job — only if there's demand. |
| 🔜 | Phone | Capture on the phone (e.g. a tiny web page or share-sheet) that syncs into the galaxy. Big job. |
