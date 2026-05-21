#!/usr/bin/env python3
"""Scan ~/project/sessions/*.jsonl for tool calls that write task-prompt files
and print (prompt, session, timestamp, tool) provenance relations.

A "prompt write" is an assistant `tool_use` of Write or Edit whose
input.file_path is under ~/project/prompts/. The session that issued the
*first* Write to a given prompt is its author; later Write/Edit calls
(same or other sessions) are revisions.

Top-level *.jsonl are interactive / orchestrator sessions; subagent logs
live in sessions/subagents/ and are excluded (subagents execute tasks,
they don't author prompts).
"""

import argparse
import glob
import json
import os
from collections import defaultdict

SESSIONS_DIR = os.path.expanduser("~/project/sessions")
MARKER = "/project/prompts/"


def scan_file(path):
    """Yield dicts for each Write/Edit tool_use targeting a prompt file."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if MARKER not in line:  # cheap pre-filter
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                if c.get("name") not in ("Write", "Edit"):
                    continue
                fp = c.get("input", {}).get("file_path", "")
                if MARKER not in fp:
                    continue
                yield {
                    "session": rec.get("sessionId", "?"),
                    "tool": c.get("name"),
                    "prompt": os.path.basename(fp),
                    "timestamp": rec.get("timestamp", ""),
                }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by-prompt", action="store_true",
                    help="group by prompt and show its author (first Write) + revisers")
    ap.add_argument("--filter", metavar="SUBSTR", default="",
                    help="only show prompts whose name contains SUBSTR")
    args = ap.parse_args()

    events = []
    for path in glob.glob(os.path.join(SESSIONS_DIR, "*.jsonl")):
        events.extend(scan_file(path))
    if args.filter:
        events = [e for e in events if args.filter in e["prompt"]]
    events.sort(key=lambda e: e["timestamp"])

    if not args.by_prompt:
        # Flat chronological list of every prompt-write tool call.
        for e in events:
            ts = e["timestamp"][:19].replace("T", " ")
            print(f"{ts:20}  {e['tool']:5}  {e['prompt']:52}  {e['session']}")
        return

    # Grouped: per prompt, the author (first Write) and any later writers.
    by_prompt = defaultdict(list)
    for e in events:
        by_prompt[e["prompt"]].append(e)
    for prompt in sorted(by_prompt):
        evs = by_prompt[prompt]
        writes = [e for e in evs if e["tool"] == "Write"]
        author = writes[0] if writes else evs[0]
        a_ts = author["timestamp"][:19].replace("T", " ")
        print(f"{prompt}")
        print(f"    author : {author['session']}  ({a_ts}, {author['tool']})")
        revisers = [e for e in evs if e is not author]
        sess_seen = {author["session"]}
        for e in revisers:
            if e["session"] in sess_seen:
                continue
            sess_seen.add(e["session"])
            ts = e["timestamp"][:19].replace("T", " ")
            print(f"    revise : {e['session']}  ({ts}, {e['tool']})")


if __name__ == "__main__":
    main()
