"""
protostar_mcp.py — lets an AI agent (like Claude Code) read your Protostar ideas.

What is this?
-------------
MCP ("Model Context Protocol") is an open standard that AI tools use to
connect to other programs. This file is a small MCP *server*: the AI tool
starts it, then asks it things like "search the ideas for 'iceland'" or
"give me idea X with its notes". It only runs while the AI tool uses it, so
it costs nothing the rest of the time.

How it talks
------------
Over "stdio": the AI tool writes one JSON message per line into this
program's input, and this program answers with one JSON line on its output.
The messages follow JSON-RPC 2.0, a simple standard: a request has a
"method" (what to do) and "params" (details), and the answer has the same
"id" plus a "result" (or an "error").

Connect it to Claude Code (once, in a terminal):
    claude mcp add protostar -- python "<full path to>/protostar_mcp.py"

What the agent can do (the "tools"):
    search_ideas   find ideas by words or #tags
    list_ideas     list ideas, newest first (filter by month, stage or tag)
    get_idea       one idea in full: text, notes, linked ideas, stage
    add_note       add a note to an idea (e.g. "started working on this")
    set_stage      mark an idea as spark / growing / done

It reads the same ideas file as the app (ideas/ideas.jsonl). To point it at
another file (for testing), set the environment variable PROTOSTAR_IDEAS.
"""

import json
import os
import sys
from pathlib import Path

from ideas_store import STAGES, TAG, Store, text_of, title_of

IDEAS_FILE = Path(os.environ.get("PROTOSTAR_IDEAS") or Path(__file__).parent / "ideas" / "ideas.jsonl")
SERVER = {"name": "protostar", "version": "1.0.0"}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


# ---------------------------------------------------------------------------
# The tools (what the agent can ask for)
# ---------------------------------------------------------------------------

def describe(idea, store, full=False):
    """An idea as readable text for the agent."""
    lines = [f"## {title_of(idea) or '(no title)'}",
             f"id: {idea['created']}  ·  stage: {idea.get('stage', 'spark')}"
             + ("  ·  pinned" if idea.get("pinned") else "")]
    text = text_of(idea)
    if full:
        if text:
            lines += ["", text]
        notes = store.notes_of(idea)
        if notes:
            lines += ["", "Notes:"] + [f"- {n['text']}  ({n['created'][:10]})" for n in notes]
        linked = store.linked_to(idea)
        if linked:
            lines += ["", "Linked ideas:"] + [f"- {title_of(o)}  (id: {o['created']})" for o in linked]
    elif text:
        flat = text.replace("\n", " ")
        lines.append(flat[:160] + ("…" if len(flat) > 160 else ""))
    return "\n".join(lines)


def find_idea(store, args):
    """Find an idea by its id, or else by (part of) its title."""
    if args.get("id"):
        idea = store.find(args["id"])
        if idea:
            return idea
    wanted = (args.get("title") or args.get("id") or "").lower().strip()
    if wanted:
        exact = [i for i in store.ideas if title_of(i).lower() == wanted]
        if exact:
            return exact[0]
        partial = [i for i in store.ideas if wanted in title_of(i).lower()]
        if partial:
            return sorted(partial, key=lambda i: i["created"], reverse=True)[0]
    raise ValueError("No idea found with that id or title. Try search_ideas first.")


def tool_search_ideas(args):
    store = Store(IDEAS_FILE)
    words = str(args.get("query", "")).lower().split()
    limit = int(args.get("limit", 20))
    found = []
    for idea in sorted(store.ideas, key=lambda i: i["created"], reverse=True):
        notes = " ".join(n["text"] for n in store.notes_of(idea))
        haystack = f"{title_of(idea)} {text_of(idea)} {notes}".lower()
        if all(w in haystack for w in words):
            found.append(describe(idea, store))
    if not found:
        return f"No ideas match {args.get('query')!r}."
    return f"{len(found)} idea(s) found" + (f" (showing {limit})" if len(found) > limit else "") + \
        ":\n\n" + "\n\n".join(found[:limit])


def tool_list_ideas(args):
    store = Store(IDEAS_FILE)
    ideas = sorted(store.ideas, key=lambda i: i["created"], reverse=True)
    if args.get("month"):
        ideas = [i for i in ideas if i["created"].startswith(args["month"])]
    if args.get("stage"):
        ideas = [i for i in ideas if i.get("stage", "spark") == args["stage"]]
    if args.get("tag"):
        tag = args["tag"].lstrip("#").lower()
        ideas = [i for i in ideas if tag in TAG.findall(
            (title_of(i) + " " + text_of(i) + " " + " ".join(n["text"] for n in store.notes_of(i))).lower())]
    limit = int(args.get("limit", 50))
    if not ideas:
        return "No ideas."
    head = f"{len(ideas)} idea(s), newest first" + (f" (showing {limit})" if len(ideas) > limit else "")
    return head + ":\n\n" + "\n\n".join(describe(i, store) for i in ideas[:limit])


def tool_get_idea(args):
    store = Store(IDEAS_FILE)
    return describe(find_idea(store, args), store, full=True)


def tool_add_note(args):
    store = Store(IDEAS_FILE)
    idea = find_idea(store, args)
    text = str(args.get("text", "")).strip()
    if not text:
        raise ValueError("The note is empty.")
    store.add_note(idea["created"], text)
    return f"Note added to “{title_of(idea)}”."


def tool_set_stage(args):
    store = Store(IDEAS_FILE)
    idea = find_idea(store, args)
    stage = str(args.get("stage", "")).lower()
    if stage not in STAGES:
        raise ValueError(f"Stage must be one of: {', '.join(STAGES)}.")
    store.set_stage(idea["created"], stage)
    return f"“{title_of(idea)}” is now: {stage}."


ID_OR_TITLE = {
    "id": {"type": "string", "description": "The idea's id (from search_ideas or list_ideas)."},
    "title": {"type": "string", "description": "Or: the idea's title (or part of it)."},
}

TOOLS = [
    {"name": "search_ideas", "function": tool_search_ideas,
     "description": "Search the user's Protostar ideas (titles, text, notes, #tags). "
                    "Every word must appear. Returns matching ideas with their ids.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words or #tags to look for."},
         "limit": {"type": "integer", "description": "Most results to return (default 20)."}},
         "required": ["query"]}},
    {"name": "list_ideas", "function": tool_list_ideas,
     "description": "List the user's Protostar ideas, newest first, optionally filtered.",
     "inputSchema": {"type": "object", "properties": {
         "month": {"type": "string", "description": "Only this month, like 2026-11."},
         "stage": {"type": "string", "enum": list(STAGES)},
         "tag": {"type": "string", "description": "Only ideas with this #tag."},
         "limit": {"type": "integer", "description": "Most ideas to return (default 50)."}}}},
    {"name": "get_idea", "function": tool_get_idea,
     "description": "Get one idea in full: its text, notes, linked ideas and stage.",
     "inputSchema": {"type": "object", "properties": ID_OR_TITLE}},
    {"name": "add_note", "function": tool_add_note,
     "description": "Add a note to an idea (for example, progress made on it).",
     "inputSchema": {"type": "object", "properties": {
         **ID_OR_TITLE, "text": {"type": "string", "description": "The note."}}, "required": ["text"]}},
    {"name": "set_stage", "function": tool_set_stage,
     "description": "Set an idea's life stage: spark (new), growing (being worked on) or done.",
     "inputSchema": {"type": "object", "properties": {
         **ID_OR_TITLE, "stage": {"type": "string", "enum": list(STAGES)}}, "required": ["stage"]}},
]


# ---------------------------------------------------------------------------
# The conversation (JSON-RPC over stdin/stdout)
# ---------------------------------------------------------------------------

def handle(message):
    """Answer one request. Returns the answer, or None for notifications."""
    method, params, msg_id = message.get("method"), message.get("params") or {}, message.get("id")
    if msg_id is None:
        return None                              # a notification: no answer expected

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {}},
                   "serverInfo": SERVER,
                   "instructions": "Protostar is the user's personal idea notebook. Use search_ideas "
                                   "or list_ideas to find an idea, then get_idea for the details."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{k: v for k, v in t.items() if k != "function"} for t in TOOLS]})
    if method == "tools/call":
        tool = next((t for t in TOOLS if t["name"] == params.get("name")), None)
        if tool is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
        try:
            text = tool["function"](params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as error:               # tell the agent what went wrong
            return ok({"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    # Read UTF-8 text in and write UTF-8 text out, whatever Windows' settings are.
    stdin = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            answer = handle(json.loads(line))
        except json.JSONDecodeError:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Not valid JSON"}}
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
