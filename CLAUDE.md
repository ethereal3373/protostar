# Protostar — working rules

Protostar is a desktop app: a quick-capture idea notepad (global shortcut -> small floating box) plus a galaxy-style map of ideas.
The owner is learning to program through this project, so how we work matters as much as the result.

## How to work

- Work in small steps. Do one step, then explain what you did in plain language (what, why, and any new concept).
  Then STOP and wait for confirmation before starting the next step.
- When you introduce a new concept (a command, a file, a library), explain it briefly the first time it appears.

## Hard requirements

- Performance: the always-running part of the app must stay very light — about 0% CPU and low memory while idle.
  Measure CPU and memory at the end of every stage and report the numbers.
- No AI features inside the app.

## Git and GitHub

- At the end of every finished step, commit to Git with a clear message and push to GitHub.
- The repository is PUBLIC. Never commit secrets, tokens, passwords, or the owner's personal notes.
- The folder where Protostar saves user ideas (`ideas/`) must always stay in `.gitignore`.
  If the save location changes, update `.gitignore` in the same step.
