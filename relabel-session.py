#!/usr/bin/env python3
"""Clone a Claude Code session JSONL with sessionIds unified.

Every event's `sessionId` field is rewritten to the new file's
filename UUID, so the entire file claims to belong to one session.
Also strips `promptId` from every event that carries one.

Why: the other scripts here (`snip-session.py`, `splice-session.py`)
preserve original sessionIds, mirroring `task_runner.py --chat`'s
chat-clone pattern -- which exists so cost_report can deduplicate
copied history by checking whether each event's sessionId matches
the filename. That pattern was designed for cloning one session,
not stitching multiple together, and Claude Code itself may key
some context-state lookups on event sessionIds. When a spliced
session contains a mix of sessionIds, stale state from the
contributing sessions can leak in. This script collapses everything
to one fresh UUID.

`promptId` is Claude Code's internal handle for "which user prompt
initiated this turn." It's stripped on the same theory: it's a
reference into the originating session's bookkeeping that doesn't
belong in a freshly-relabeled session. `task_runner.py --chat`
strips it for the same reason.

Output goes to ~/.claude/projects/-home-claude/<new-uuid>.jsonl.
Prints the new session UUID on stdout.

Usage:
    relabel-session.py <source.jsonl>
"""

import json
import os
import sys
import uuid
from collections import Counter

HOME_BUCKET = os.path.expanduser("~/.claude/projects/-home-claude")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <source.jsonl>", file=sys.stderr)
        return 2
    src = sys.argv[1]
    if not os.path.exists(src):
        print(f"Error: source file not found: {src}", file=sys.stderr)
        return 1

    new_id = str(uuid.uuid4())
    dst = os.path.join(HOME_BUCKET, f"{new_id}.jsonl")
    if os.path.exists(dst):
        print(f"Error: destination exists (UUID collision?): {dst}", file=sys.stderr)
        return 1

    src_bytes = os.path.getsize(src)
    n_events = 0
    sessionid_before = Counter()
    rewrote_sessionid = 0
    stripped_promptid = 0

    os.makedirs(HOME_BUCKET, exist_ok=True)
    with open(src) as fin, open(dst, "w") as fout:
        for line in fin:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                fout.write(line + "\n")
                continue
            n_events += 1

            # Tally and rewrite sessionId
            sid = event.get("sessionId")
            if sid:
                sessionid_before[sid] += 1
                if sid != new_id:
                    event["sessionId"] = new_id
                    rewrote_sessionid += 1

            # Strip promptId
            if "promptId" in event:
                del event["promptId"]
                stripped_promptid += 1

            fout.write(json.dumps(event) + "\n")

    dst_bytes = os.path.getsize(dst)
    print(f"Cloned {n_events} events: {src_bytes:,} -> {dst_bytes:,} bytes",
          file=sys.stderr)
    print(f"  rewrote sessionId on {rewrote_sessionid} events", file=sys.stderr)
    print(f"  stripped promptId from {stripped_promptid} events", file=sys.stderr)
    print(f"  original sessionId distribution:", file=sys.stderr)
    for sid, n in sessionid_before.most_common():
        print(f"    {sid}: {n}", file=sys.stderr)
    print(f"New session UUID: {new_id}", file=sys.stderr)
    print(f"Path: {dst}", file=sys.stderr)
    print(new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
