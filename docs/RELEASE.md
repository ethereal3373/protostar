# Making Protostar downloadable — and letting people know it exists

## Can people download it today?

Technically yes: the code is public on GitHub. But today a person would have to:

1. install Python 3,
2. download the code (`git clone https://github.com/ethereal3373/protostar` or "Code → Download ZIP"),
3. open a terminal in the folder and run `python -m pip install -r requirements.txt`,
4. run `python startup.py install`.

That works for programmers. Almost everyone else gives up at step 1. So the
goal is: **one download, double-click, done.**

## Steps to a real download

### 0. Decide the license (your decision)
Right now the repository has **no license**, which legally means "all rights
reserved": people can look at the code but not reuse it. Common choices:
- **MIT** — anyone can use, change and share it, even commercially, as long as
  they keep your name. Simple and the most popular. (Recommended for a
  learning project you want people to use.)
- **GPL-3.0** — like MIT, but anyone who shares a changed version must also
  share their code.
Add the chosen text as a `LICENSE` file (GitHub can create it for you: *Add
file → Create new file → name it LICENSE → "Choose a license template"*).

### 1. Move the data out of the program folder (needed first)
Installed programs live in *C:\Program Files*, where they're not allowed to
write files. Ideas and settings must move to `%APPDATA%\Protostar` (your
personal app-data folder), with an automatic move of existing ideas. This is
a code change I can do next.

### 2. Turn it into .exe files — PyInstaller
PyInstaller packs Python, the libraries and the code into ready-to-run `.exe`
files, so users don't need Python.
```
python -m pip install pyinstaller
pyinstaller --noconsole --name Protostar --add-data "fonts;fonts" protostar.py
```
(The galaxy app and the AI connection get their own entries; I'd write a
"build script" so it's one command.) Test the result on a PC *without*
Python — e.g. a friend's laptop or the free *Windows Sandbox*.

### 3. Make an installer — Inno Setup (free)
An installer gives people the familiar *Setup.exe*: Start-menu entry,
"Start with Windows" checkbox, and a proper uninstaller.
Inno Setup turns a small script into `Protostar-Setup-0.1.0.exe`.

### 4. Version numbers
Use `0.1.0` for the first public test ("beta"), then `0.2.0` for new
features, `0.1.1` for fixes. Show the version in Settings.

### 5. Publish on GitHub Releases
On GitHub: *Releases → Draft a new release → tag `v0.1.0`*, write what's new,
attach the Setup.exe. The download link is then
`https://github.com/ethereal3373/protostar/releases/latest`.

### 6. The "Windows protected your PC" warning
New programs that aren't "code-signed" show this blue warning. Options:
- **Live with it at first** — explain on the download page: *More info → Run anyway*.
- **Microsoft's Trusted Signing** (about $10/month) or a classic code-signing
  certificate (about $100–400/year) removes it over time.

### 7. Updates
A small "Check for updates" in Settings that asks GitHub for the latest
release and offers a link. (Fully automatic updates can come later.)

### 8. A page people can land on
Use **GitHub Pages** (free): a one-page website with a short video of the
galaxy, three sentences about what it does, a big *Download for Windows*
button, and "Your ideas never leave your PC".

## Letting people know it exists

**What makes Protostar stand out** — lead with this everywhere:
1. *Your ideas become a galaxy that grows as you think.* It's visual and unusual: perfect for short videos.
2. *Catch an idea in 2 seconds from anywhere* (the shortcut).
3. *Private and offline, no account, no AI inside* — but your own AI agent can read it (MCP).
4. *Built while learning to code* — people love that story.

**Make the material first**
- A 20–30 second screen recording: press the shortcut → type an idea → the
  star is born → zoom out → the Timeline replays months of ideas forming a
  galaxy. Use the demo galaxy (and a bigger demo) so it looks full.
- 3–4 good screenshots for the README and the page.

**Where to post** (one at a time, and answer every comment)
- **Reddit**: r/SideProject, r/productivity, r/PKMS (personal knowledge
  management), r/Python ("Showcase" flair), r/ClaudeAI (the MCP angle).
  Each subreddit has rules about self-promotion: read them first.
- **Hacker News**: a "Show HN: Protostar – your ideas as a growing 3D galaxy" post.
- **Product Hunt**: a launch day, with the video. Ask a few friends to
  support it on the day.
- **MCP directories** (people looking for things to connect to Claude):
  the "awesome-mcp-servers" list on GitHub, mcp.so, Glama, Smithery.
- **Short videos**: TikTok / YouTube Shorts / Instagram Reels of the galaxy
  growing — this kind of visual does well there.
- **Writing**: a post on dev.to or Medium: "I built a galaxy for my ideas
  while learning Python" — the learning story plus screenshots.
- **AlternativeTo.net**: list it as an alternative to note apps
  (Obsidian, Google Keep, Notion), so people searching find it.

**Before posting**: have 3–5 friends try the installer and tell you where
they got stuck. Fix those first — first impressions are everything.

**After posting**: GitHub "Issues" is where people report bugs and wishes.
Add a short "Feedback welcome" line to the README.
