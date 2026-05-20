#!/usr/bin/env python3
"""Clone a Claude Code session JSONL with stale session-state scrubbed.

Three independent scrubs, all opt-out via flags but on by default:

1. **sessionId unification** -- every event's `sessionId` field is
   rewritten to the new file's filename UUID, so the entire file
   claims to belong to one session. (`--no-rewrite-session-id`
   leaves them alone.)

2. **promptId strip** -- removes the `promptId` field from every
   event. (`--no-strip-promptid` leaves them in.)

3. **usage zeroing** -- on every assistant event, sets
   `message.usage.input_tokens`, `cache_creation_input_tokens`,
   `cache_read_input_tokens`, and `output_tokens` to 0. Claude
   Code reads these to compute the displayed context-usage
   percentage; stale values from a session that hit its limit
   keep the bar pinned at 96% even after content has been
   trimmed. (`--no-zero-usage` leaves them in.)

Why this exists: the other scripts here (`snip-session.py`,
`splice-session.py`) preserve original sessionIds, mirroring
`task_runner.py --chat`'s chat-clone pattern. That pattern exists
so cost_report can deduplicate copied history by checking whether
each event's sessionId matches the filename. It's the right
choice for cost accounting, but when a session has been stitched
from multiple sources or trimmed past a context-limit incident,
Claude Code can still find stale state from the original sessions
and keep refusing to make API calls. This script does the
"make it look like a brand-new session" cleanup.

Output goes to ~/.claude/projects/-home-claude/<new-uuid>.jsonl.
Prints the new session UUID on stdout.

Usage:
    relabel-session.py [flags] <source.jsonl>
"""

import argparse
import json
import os
import sys
import uuid
from collections import Counter

HOME_BUCKET = os.path.expanduser("~/.claude/projects/-home-claude")


_TOKEN_KEYS = ("input_tokens", "output_tokens",
               "cache_creation_input_tokens", "cache_read_input_tokens")
_CACHE_CREATION_KEYS = ("ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens")


def _zero_usage_dict(usage):
    """Zero token counters in one usage-shaped dict (top level or iteration).

    Returns True if anything was modified.
    """
    touched = False
    for k in _TOKEN_KEYS:
        if k in usage and usage[k]:
            usage[k] = 0
            touched = True
    cc = usage.get("cache_creation")
    if isinstance(cc, dict):
        for k in _CACHE_CREATION_KEYS:
            if k in cc and cc[k]:
                cc[k] = 0
                touched = True
    return touched


def zero_assistant_usage(event):
    """Zero out token counts in an assistant event's usage block.

    Handles both the top-level usage dict and the nested `iterations`
    array, which carries per-iteration token counts that Claude Code
    can read independently.

    Returns True if anything was modified.
    """
    if event.get("type") != "assistant":
        return False
    msg = event.get("message")
    if not isinstance(msg, dict):
        return False
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return False
    touched = _zero_usage_dict(usage)
    iterations = usage.get("iterations")
    if isinstance(iterations, list):
        for it in iterations:
            if isinstance(it, dict):
                if _zero_usage_dict(it):
                    touched = True
    return touched


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--no-rewrite-session-id", action="store_true",
                    help="Leave event sessionId fields alone")
    ap.add_argument("--no-strip-promptid", action="store_true",
                    help="Leave promptId fields in place")
    ap.add_argument("--no-zero-usage", action="store_true",
                    help="Leave assistant usage token counts in place")
    args = ap.parse_args()

    src = args.source
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
    zeroed_usage = 0

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
                if not args.no_rewrite_session_id and sid != new_id:
                    event["sessionId"] = new_id
                    rewrote_sessionid += 1

            # Strip promptId
            if not args.no_strip_promptid and "promptId" in event:
                del event["promptId"]
                stripped_promptid += 1

            # Zero assistant usage counters
            if not args.no_zero_usage:
                if zero_assistant_usage(event):
                    zeroed_usage += 1

            fout.write(json.dumps(event) + "\n")

    dst_bytes = os.path.getsize(dst)
    print(f"Cloned {n_events} events: {src_bytes:,} -> {dst_bytes:,} bytes",
          file=sys.stderr)
    print(f"  rewrote sessionId on {rewrote_sessionid} events", file=sys.stderr)
    print(f"  stripped promptId from {stripped_promptid} events", file=sys.stderr)
    print(f"  zeroed usage on {zeroed_usage} assistant events", file=sys.stderr)
    print(f"  original sessionId distribution:", file=sys.stderr)
    for sid, n in sessionid_before.most_common():
        print(f"    {sid}: {n}", file=sys.stderr)
    print(f"New session UUID: {new_id}", file=sys.stderr)
    print(f"Path: {dst}", file=sys.stderr)
    print(new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
