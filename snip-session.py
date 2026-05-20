#!/usr/bin/env python3
"""Snip a Claude Code session JSONL at a chosen user message.

Finds the first user-input event whose text starts with (or contains)
the given pattern, then writes a new session JSONL containing every
event STRICTLY BEFORE that user message. The matched user message and
everything after it is dropped.

A "user-input" event is a `type:"user"` event whose `message.content`
contains no tool_result blocks — i.e., an actual user-typed message,
not a tool result that the protocol wraps in a user role.

Output goes to ~/.claude/projects/-home-claude/<new-uuid>.jsonl,
mirroring the chat-clone pattern from `task_runner.py --chat`. The
original session JSONL is not modified.

Usage:
    snip-session.py <source.jsonl> <match-text>
    snip-session.py --substring <source.jsonl> <match-text>
    snip-session.py --list <source.jsonl>           # preview user msgs

Prints the new session UUID on stdout.
"""

import argparse
import json
import os
import sys
import uuid

HOME_BUCKET = os.path.expanduser("~/.claude/projects/-home-claude")


def extract_user_text(event):
    """If this is a real user-input message, return its concatenated text.

    Returns None for tool_result-bearing user events or non-user events.
    """
    if event.get("type") != "user":
        return None
    msg = event.get("message") or {}
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    text_parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        bt = block.get("type")
        if bt == "tool_result":
            return None  # tool-result wrapper, not a real user input
        if bt == "text":
            text_parts.append(block.get("text", ""))
    return "".join(text_parts) if text_parts else None


def iter_user_inputs(path):
    """Yield (line_number, text) for every real user-input event."""
    with open(path) as f:
        for i, line in enumerate(f, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = extract_user_text(event)
            if text is not None and text.strip():
                yield i, text


def extract_assistant_text(event):
    """Concatenate text from an assistant event's content blocks."""
    if event.get("type") != "assistant":
        return None
    msg = event.get("message") or {}
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if not isinstance(content, list):
        return None
    parts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "".join(parts) if parts else None


def iter_assistant_texts(path):
    """Yield (line_number, text) for every assistant event with text."""
    with open(path) as f:
        for i, line in enumerate(f, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = extract_assistant_text(event)
            if text is not None and text.strip():
                yield i, text


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="Source session JSONL")
    ap.add_argument("match", nargs="?", default=None,
                    help="Pattern to match against the chosen role's message")
    ap.add_argument("--substring", action="store_true",
                    help="Match as substring (default: prefix for user, substring for assistant)")
    ap.add_argument("--at-assistant", action="store_true",
                    help="Match an assistant message instead of a user message. "
                         "Keeps the matching message (drops everything after it). "
                         "Defaults to substring matching.")
    ap.add_argument("--list", action="store_true",
                    help="List messages of the chosen role with line numbers and exit")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"Error: source file not found: {args.source}", file=sys.stderr)
        return 1

    if args.list:
        iter_fn = iter_assistant_texts if args.at_assistant else iter_user_inputs
        for line_no, text in iter_fn(args.source):
            head = text.lstrip().replace("\n", " ")
            print(f"line {line_no:>5}: {head[:140]}")
        return 0

    if not args.match:
        print("Error: missing match pattern (or use --list)", file=sys.stderr)
        return 2

    if args.at_assistant:
        # Find the matching assistant; cut AFTER it (cut_line = match_line + 1)
        target = args.match
        substring = True if not args.substring else True  # default to substring
        # Allow explicit prefix mode if user really wants it
        substring = True
        match_line = None
        matched_text = None
        for line_no, text in iter_assistant_texts(args.source):
            if target in text:
                match_line = line_no
                matched_text = text
                break
        if match_line is None:
            print(f"Error: no assistant message matched: {args.match[:80]!r}",
                  file=sys.stderr)
            return 1
        cut_line = match_line + 1
        print(f"Matched assistant at line {match_line}; cut after (line {cut_line})",
              file=sys.stderr)
        print(f"Matched text tail: ...{matched_text[-200:]!r}", file=sys.stderr)
    else:
        target = args.match.lstrip()
        cut_line = None
        matched_text = None
        for line_no, text in iter_user_inputs(args.source):
            head = text.lstrip()
            ok = (target in head) if args.substring else head.startswith(target)
            if ok:
                cut_line = line_no
                matched_text = head
                break

        if cut_line is None:
            print(f"Error: no user message matched: {args.match[:80]!r}",
                  file=sys.stderr)
            return 1

    print(f"Cut point: line {cut_line}", file=sys.stderr)
    if not args.at_assistant:
        print(f"Matched user text (first 200 chars): "
              f"{matched_text[:200].replace(chr(10),' ')!r}", file=sys.stderr)

    new_id = str(uuid.uuid4())
    dst = os.path.join(HOME_BUCKET, f"{new_id}.jsonl")
    if os.path.exists(dst):
        print(f"Error: destination exists (UUID collision?): {dst}", file=sys.stderr)
        return 1

    os.makedirs(HOME_BUCKET, exist_ok=True)
    src_bytes = os.path.getsize(args.source)
    kept_lines = 0
    kept_bytes = 0
    with open(args.source) as fin, open(dst, "w") as fout:
        for i, line in enumerate(fin, 1):
            if i >= cut_line:
                break
            fout.write(line)
            kept_lines += 1
            kept_bytes += len(line)

    pct_kept = kept_bytes * 100.0 / src_bytes if src_bytes else 0.0
    print(f"Kept {kept_lines} events ({kept_bytes:,} bytes) "
          f"out of {src_bytes:,} ({pct_kept:.1f}% kept)", file=sys.stderr)
    print(f"New session UUID: {new_id}", file=sys.stderr)
    print(f"Path: {dst}", file=sys.stderr)
    print(new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
