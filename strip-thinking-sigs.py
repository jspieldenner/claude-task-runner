#!/usr/bin/env python3
"""Clone a Claude Code session JSONL with bulky content stripped.

Mirrors the cloning pattern used by `task_runner.py --chat`:
  - generates a fresh session UUID
  - writes the new JSONL into ~/.claude/projects/-home-claude/<uuid>.jsonl
  - preserves each event's original sessionId field (so cost accounting
    can deduplicate copied history against the live original)

By default only the cheapest, safest cut runs (`--strip-signatures`,
which blanks every thinking block's `signature` field). The other
passes are opt-in via flags, with `--aggressive` enabling all of
them at sensible defaults.

Cuts:
  --strip-signatures        (default: on)
        Blank every thinking block's `signature`. Removes encrypted
        chain-of-reasoning bytes; preserves block structure.

  --strip-images
        Replace every image inside a tool_result with a small text
        stub. Strips base64 image data (which tokenizes heavily).

  --strip-session-start
        Truncate the `stdout` of SessionStart-hook attachments
        (e.g. the lightrag-entities priming block). Keeps a short
        head + a "[N bytes stripped]" tail.

  --truncate-tool-results [N]
        Truncate any tool_result text body whose length exceeds N
        bytes (default 4096) to "first 1500 chars + ...truncated...
        + last 500 chars". Both list-of-blocks and bare-string
        content shapes are handled.

  --aggressive
        Enable strip-images, strip-session-start, and
        truncate-tool-results at defaults.

A session cloned this way is summarizable (the /end skill can read
it) but is NOT resumable against the API: signatures are required
for thinking-block continuity on the wire, and tool_result content
mismatches break replay. That's the trade-off.

Usage:
    strip-thinking-sigs.py [flags] <source.jsonl>

Prints the new session UUID on stdout.
"""

import argparse
import json
import os
import sys
import uuid

HOME_BUCKET = os.path.expanduser("~/.claude/projects/-home-claude")


def strip_signatures(event):
    """Blank every thinking block's signature. Returns bytes saved."""
    msg = event.get("message")
    if not isinstance(msg, dict):
        return 0
    content = msg.get("content")
    if not isinstance(content, list):
        return 0
    saved = 0
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            if block.get("signature"):
                saved += len(block["signature"])
                block["signature"] = ""
    return saved


def truncate_text(text, threshold, head=1500, tail=500):
    """If text exceeds threshold, keep head + tail with a stripped marker.

    Returns (new_text, bytes_saved).
    """
    if len(text) <= threshold:
        return text, 0
    cut = len(text) - head - tail
    new = text[:head] + f"\n\n...[{cut:,} bytes stripped]...\n\n" + text[-tail:]
    return new, len(text) - len(new)


def strip_images_and_truncate(event, *, strip_images, truncate_thresh):
    """Process every tool_result block. Returns (img_saved, trunc_saved)."""
    img_saved = 0
    trunc_saved = 0
    msg = event.get("message")
    if not isinstance(msg, dict):
        return 0, 0
    content = msg.get("content")
    if not isinstance(content, list):
        return 0, 0
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        c = block.get("content")
        if isinstance(c, list):
            new_list = []
            for sub in c:
                if not isinstance(sub, dict):
                    new_list.append(sub)
                    continue
                st = sub.get("type")
                if st == "image" and strip_images:
                    src = sub.get("source", {}) or {}
                    data = src.get("data", "") or ""
                    img_saved += len(data)
                    new_list.append({"type": "text", "text": "[image stripped]"})
                elif st == "text" and truncate_thresh:
                    t = sub.get("text", "") or ""
                    new_t, saved = truncate_text(t, truncate_thresh)
                    trunc_saved += saved
                    new_list.append({"type": "text", "text": new_t})
                else:
                    new_list.append(sub)
            block["content"] = new_list
        elif isinstance(c, str) and truncate_thresh:
            new_t, saved = truncate_text(c, truncate_thresh)
            trunc_saved += saved
            block["content"] = new_t
    return img_saved, trunc_saved


def strip_session_start_attachment(event, *, head=200):
    """Truncate large SessionStart hook attachment stdout. Returns bytes saved."""
    if event.get("type") != "attachment":
        return 0
    attach = event.get("attachment", {}) or {}
    if not isinstance(attach, dict):
        return 0
    if attach.get("hookEvent") != "SessionStart":
        return 0
    stdout = attach.get("stdout") or ""
    if len(stdout) <= head + 50:
        return 0
    saved = len(stdout) - head
    attach["stdout"] = stdout[:head] + f"...[{saved:,} bytes stripped]"
    return saved


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--no-strip-signatures", action="store_true",
                    help="Leave thinking signatures in place")
    ap.add_argument("--strip-images", action="store_true",
                    help="Replace base64 image data in tool_results with a stub")
    ap.add_argument("--strip-session-start", action="store_true",
                    help="Truncate SessionStart hook attachment stdouts")
    ap.add_argument("--truncate-tool-results", nargs="?", type=int, const=4096,
                    default=None, metavar="N",
                    help="Truncate tool_result text bodies over N bytes (default 4096)")
    ap.add_argument("--aggressive", action="store_true",
                    help="Enable --strip-images, --strip-session-start, "
                         "and --truncate-tool-results at defaults")
    args = ap.parse_args()

    if args.aggressive:
        args.strip_images = True
        args.strip_session_start = True
        if args.truncate_tool_results is None:
            args.truncate_tool_results = 4096

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
    saved_sig = 0
    saved_img = 0
    saved_trunc = 0
    saved_ss = 0
    n_events = 0

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
            if not args.no_strip_signatures:
                saved_sig += strip_signatures(event)
            if args.strip_images or args.truncate_tool_results:
                i, t = strip_images_and_truncate(
                    event,
                    strip_images=args.strip_images,
                    truncate_thresh=args.truncate_tool_results,
                )
                saved_img += i
                saved_trunc += t
            if args.strip_session_start:
                saved_ss += strip_session_start_attachment(event)
            fout.write(json.dumps(event) + "\n")
            n_events += 1

    dst_bytes = os.path.getsize(dst)
    pct = (src_bytes - dst_bytes) * 100.0 / src_bytes if src_bytes else 0.0
    print(f"Cloned {n_events} events: {src_bytes:,} -> {dst_bytes:,} bytes "
          f"({pct:.1f}% smaller)", file=sys.stderr)
    print(f"  signatures:    {saved_sig:>12,} bytes", file=sys.stderr)
    print(f"  images:        {saved_img:>12,} bytes", file=sys.stderr)
    print(f"  session-start: {saved_ss:>12,} bytes", file=sys.stderr)
    print(f"  tool_results:  {saved_trunc:>12,} bytes (threshold "
          f"{args.truncate_tool_results})", file=sys.stderr)
    print(f"New session UUID: {new_id}", file=sys.stderr)
    print(f"Path: {dst}", file=sys.stderr)
    print(new_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
