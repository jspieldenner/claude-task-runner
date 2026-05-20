#!/usr/bin/env python3
"""Splice the tail of one Claude Code session onto another.

The complement of `snip-session.py`. Where snip drops the matched
user message and everything after it, splice takes that same tail
(matched message + everything after) and grafts it onto the bottom
of a different existing session, producing a new session.

Typical flow:
  1. `snip-session.py orig.jsonl "now, I've noticed..."`  -> a.jsonl
  2. Resume a.jsonl, run /end, etc. Session file gets appended to.
  3. `splice-session.py a.jsonl orig.jsonl "now, I've noticed..."`
     -> new.jsonl, containing all of a.jsonl plus the tail of orig.

Mechanics:
  - Concatenates events from PREFIX, then events from TAIL_SOURCE
    starting at the matched user message.
  - The first chain-participating event in the tail (one with both a
    `uuid` and a `parentUuid`) has its `parentUuid` rewritten to the
    last chain-participating uuid in the prefix. This keeps the
    conversation tree linked across the splice.
  - Every event keeps its original `sessionId` (mirroring the chat
    clone pattern in task_runner.py: copied history can be deduped
    by cost accounting against the new file's UUID).
  - Non-chain metadata events (bridge-session, last-prompt, ai-title,
    etc.) from both files are passed through in order. The tail's
    later state wins for any single-value metadata.

Output goes to ~/.claude/projects/-home-claude/<new-uuid>.jsonl.
Prints the new session UUID on stdout.

Usage:
    splice-session.py <prefix.jsonl> <tail-source.jsonl> <match-text>
    splice-session.py --substring <prefix.jsonl> <tail-source.jsonl> <match-text>

Caveat: same as the other trim scripts -- a spliced session is
viewable in the Claude Code TUI and readable by /end, but may not
be cleanly API-resumable across the splice boundary if either side
had tool_use blocks that don't pair up.
"""

import argparse
import json
import os
import sys
import uuid

HOME_BUCKET = os.path.expanduser("~/.claude/projects/-home-claude")


def extract_user_text(event):
    """Return concatenated text of a real user-input event, else None."""
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
            return None
        if bt == "text":
            text_parts.append(block.get("text", ""))
    return "".join(text_parts) if text_parts else None


def find_tail_start(path, match, substring):
    """Return the line number of the first user-input event matching `match`."""
    target = match.lstrip()
    with open(path) as f:
        for i, line in enumerate(f, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = extract_user_text(event)
            if text is None:
                continue
            head = text.lstrip()
            ok = (target in head) if substring else head.startswith(target)
            if ok:
                return i, head
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prefix", help="Existing session to extend (its events come first)")
    ap.add_argument("tail_source", help="Session to take the tail from")
    ap.add_argument("match", help="Pattern matching the user message where tail starts")
    ap.add_argument("--substring", action="store_true",
                    help="Match as substring (default: prefix)")
    args = ap.parse_args()

    if not os.path.exists(args.prefix):
        print(f"Error: prefix file not found: {args.prefix}", file=sys.stderr)
        return 1
    if not os.path.exists(args.tail_source):
        print(f"Error: tail-source file not found: {args.tail_source}", file=sys.stderr)
        return 1

    # 1. Find tail cut point
    cut_line, matched_text = find_tail_start(args.tail_source, args.match, args.substring)
    if cut_line is None:
        print(f"Error: no user message matched in tail source: {args.match[:80]!r}",
              file=sys.stderr)
        return 1
    print(f"Tail starts at line {cut_line} of {os.path.basename(args.tail_source)}",
          file=sys.stderr)
    print(f"Matched: {matched_text[:120].replace(chr(10), ' ')!r}", file=sys.stderr)

    # 2. Read prefix; find last chain-participating uuid
    prefix_events = []
    last_chain_uuid = None
    with open(args.prefix) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                prefix_events.append(line)  # pass through raw
                continue
            prefix_events.append(event)
            if event.get("uuid") and event.get("parentUuid") is not None:
                last_chain_uuid = event["uuid"]
            elif event.get("uuid") and "parentUuid" in event:
                # Root event (parentUuid: null) still counts as chain participant
                last_chain_uuid = event["uuid"]

    if last_chain_uuid is None:
        print("Warning: prefix has no chain-participating events; tail will not be rewired",
              file=sys.stderr)

    # 3. Read tail events
    tail_events = []
    with open(args.tail_source) as f:
        for i, line in enumerate(f, 1):
            if i < cut_line:
                continue
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                tail_events.append(json.loads(line))
            except json.JSONDecodeError:
                tail_events.append(line)

    # 4. Rewire first chain-participating event in tail
    rewired = False
    for ev in tail_events:
        if not isinstance(ev, dict):
            continue
        if ev.get("uuid") and "parentUuid" in ev:
            if last_chain_uuid is not None:
                old_parent = ev.get("parentUuid")
                ev["parentUuid"] = last_chain_uuid
                print(f"Rewired tail start parent: {str(old_parent)[:8]} -> "
                      f"{last_chain_uuid[:8]}", file=sys.stderr)
                rewired = True
            break

    if not rewired and last_chain_uuid is not None:
        print("Warning: no chain-participating event found at tail start", file=sys.stderr)

    # 5. Write new session
    new_id = str(uuid.uuid4())
    dst = os.path.join(HOME_BUCKET, f"{new_id}.jsonl")
    if os.path.exists(dst):
        print(f"Error: destination exists (UUID collision?): {dst}", file=sys.stderr)
        return 1

    os.makedirs(HOME_BUCKET, exist_ok=True)
    with open(dst, "w") as f:
        for ev in prefix_events:
            if isinstance(ev, str):
                f.write(ev + "\n")
            else:
                f.write(json.dumps(ev) + "\n")
        for ev in tail_events:
            if isinstance(ev, str):
                f.write(ev + "\n")
            else:
                f.write(json.dumps(ev) + "\n")

    dst_bytes = os.path.getsize(dst)
    print(f"Wrote {len(prefix_events) + len(tail_events)} events "
          f"({len(prefix_events)} prefix + {len(tail_events)} tail), "
          f"{dst_bytes:,} bytes", file=sys.stderr)
    print(f"New session UUID: {new_id}", file=sys.stderr)
    print(f"Path: {dst}", file=sys.stderr)
    print(new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
