---
name: end
description: Closing ritual for a task or session — produces a compaction summary. Use as the final step of every task runner task, or by hand at the end of an interactive session.
---

# end — closing ritual: compaction

One artifact, one audience:

| Artifact | Audience | Path |
|----------|----------|------|
| Compaction summary | A future Claude picking the session back up | `~/project/compactions/session-<ID>.md` |

The compaction is named by session ID, so re-running
`end` in the same session lands on the same paths — useful both for
detecting re-runs (common when the user keeps adding work after an
earlier `/end`) and for keeping each session's debrief in one place.

**Session ID format.** `<ID>` is normally the 36-char session UUID,
e.g. `72f1d8c2-18c8-4deb-9f3e-11a49f361f21`. When `end` runs inside
a task-runner subagent, the subagent's JSONL lives at
`~/project/sessions/subagents/<parent>/agent-<aid>.jsonl` and the
session ID becomes the **composite** `<parent-UUID>-<aid>` (54 chars,
e.g. `72f1d8c2-18c8-4deb-9f3e-11a49f361f21-a03e8c071b2ad7f97`). Each
subagent run thus gets its own compaction; multiple subagents under
the same parent don't collide. Detection is automatic — see Step 1
of the first-run workflow.

Sibling docs in this skill directory hold the per-artifact detail:

- `COMPACT.md` — the compaction file's two-part layout.
- `COMPACT_PROMPT.md` — the `<analysis>` + `<summary>` template
  for the compaction's second half.

## First run vs re-run

This skill is idempotent within a session. On a first invocation it
produces an artifact; on a re-run (the user kept working after
an earlier `/end`) it UPDATES the artifact rather than producing
a duplicate.

**Detect the case before doing anything else:**

- If you remember invoking `/end` earlier in the same conversation,
  this is a **re-run**. You already know the session UUID — skip
  the marker dance and proceed to "Re-run procedure" below.
- If you're not sure (context was compacted, this is a continuation
  session), look for a compaction file with a recent mtime:
  ```bash
  find ~/project/compactions -name 'session-*.md' -mmin -120 -printf '%T+ %f\n'
  ```
  If exactly one matches, use its UUID. If multiple match (rare,
  only when concurrent sessions overlap) or zero match, fall back
  to the first-run workflow's marker dance.
- Otherwise this is a **first run**; follow "First-run workflow"
  below.

## Re-run procedure

You're updating, not creating. The hard part is enumerating what's
new since the last `/end`; the file IO that follows is mechanical.

### Step 1 — verify the session ID hasn't changed

For a top-level (36-char UUID) session:
```bash
find ~/.claude/projects/ -maxdepth 2 -name "<ID>.jsonl" -print -quit
```

For a subagent composite ID (`<parent>-<aid>`, 54 chars), the live
JSONL is under `~/.claude/projects/` (the backup under
`~/project/sessions/subagents/` only exists post-`--complete`, so
check both):
```bash
parent=${ID:0:36}; aid=${ID:37}
{ test -f ~/.claude/projects/*/${parent}/subagents/agent-${aid}.jsonl \
  || test -f ~/project/sessions/subagents/${parent}/agent-${aid}.jsonl; } \
  && echo same-session
```

If the file exists, you're still in the same session and the ID is
good. If it doesn't (rare — session was migrated), fall back to the
first-run workflow's marker dance to derive the new ID, then proceed.

### Step 2 — read the existing compaction

Path: `~/project/compactions/session-<ID>.md`. Pull one thing out:

- **Boundary.** The compaction's `<analysis>` block stops at some
  point in the conversation. Anything past that point is "new
  work" to fold in.

### Step 3 — enumerate the new work

Hold the list in your head before touching files. Ask:

- What did the user ask for since the last `/end`?
- What did you build, decide, measure, or discover?
- Which files were edited or created?
- Which commits landed in which repos?
- Which previous "open items" or "known gaps" got resolved?
- Were there corrections to the previous `/end`'s claims —
  anything that turned out to be wrong and should be set right?

### Step 4 — overwrite the compaction cumulatively

Per `COMPACT.md`'s re-run rule. The reader is a future Claude; they
only need the latest snapshot covering the whole session through
now, not a diff log.

### Step 5 — report the path

One line per compaction.  Nothing else.

---

## First-run workflow

The session ID is needed for the compaction, so:

1. Kick off session-ID detection in the background.
2. Wait for the session ID to arrive.
3. Use the session ID to write the compaction.

### Step 1 — kick off session-ID detection (background)

The session ID isn't an env var. Detection works by emitting a
random marker, waiting for it to flush to a `.jsonl` file, then
grepping the session directories to find the match. The flush takes
a few seconds, so do it in background.

Subagents log to a different place than top-level sessions, and the
poller must hit the location Claude Code writes **in real time**
(while this skill is still running inside the subagent), not a
backup copy that only appears after the subagent exits:

- **Top-level sessions** flush to
  `~/.claude/projects/<bucket>/<UUID>.jsonl` (depth 2 under
  `~/.claude/projects/`). The ID is the basename.
- **Task-runner subagents** flush, in real time, to
  `~/.claude/projects/<bucket>/<parent>/subagents/agent-<aid>.jsonl`
  (depth 4 under `~/.claude/projects/`). The ID is the composite
  `<parent>-<aid>`. Note the `<parent>` directory is *above*
  `subagents/`. A backup hardlink at
  `~/project/sessions/subagents/<parent>/agent-<aid>.jsonl` is
  created by `task_runner.py --complete` — but that runs only
  *after* the subagent exits, so it does **not** exist yet while
  `end` is running. The poller must therefore search the live
  `~/.claude/projects/` tree, not the backup tree.

```bash
# Foreground: emit marker
marker="SID_$(openssl rand -hex 8)"; echo "$marker"
```

Then launch the poller via Bash with `run_in_background: true`
(replacing `<MARKER>` with the value just emitted):

```bash
until path=$( { \
        find ~/.claude/projects/ -maxdepth 4 -name '*.jsonl' -mmin -2 \
             -exec grep -l "<MARKER>" {} + 2>/dev/null; \
        find ~/project/sessions/subagents/ -maxdepth 2 -name 'agent-*.jsonl' -mmin -2 \
             -exec grep -l "<MARKER>" {} + 2>/dev/null; \
      } | head -1); \
      [ -n "$path" ]; do sleep 2; done
# Translate path to session ID. Three possible shapes:
#   ~/.claude/projects/<bucket>/<parent>/subagents/agent-<aid>.jsonl  (live subagent — parent ABOVE subagents/)
#   ~/project/sessions/subagents/<parent>/agent-<aid>.jsonl           (post-complete backup — parent BELOW subagents/)
#   ~/.claude/projects/<bucket>/<UUID>.jsonl                          (top-level session)
case "$path" in
  */subagents/agent-*.jsonl)            # live subagent: <parent>/subagents/agent-<aid>.jsonl
    aid=$(basename "$path" .jsonl); aid=${aid#agent-}
    parent=$(basename "$(dirname "$(dirname "$path")")")
    echo "${parent}-${aid}" ;;
  */subagents/*/agent-*.jsonl)          # backup hardlink: subagents/<parent>/agent-<aid>.jsonl
    parent=$(basename "$(dirname "$path")")
    aid=$(basename "$path" .jsonl); aid=${aid#agent-}
    echo "${parent}-${aid}" ;;
  *) basename "$path" .jsonl ;;
esac
```

The bash run ID lets you check the output later via `BashOutput`.

**Why this layout matters.** The marker the subagent emits is
written only to the subagent's own JSONL — the live one under
`~/.claude/projects/<bucket>/<parent>/subagents/`, four levels deep.
An earlier version of this poller capped the first `find` at
`-maxdepth 2` (so it never reached depth-4 subagent files) and
relied on the second `find` over `~/project/sessions/subagents/`
for subagents. But that backup tree is populated by
`--complete` *after* the subagent exits, so during the `end` run it
is empty: the poller timed out and the agent fell back to "find the
recently-touched top-level JSONL" — which yielded the *parent
session's* UUID, not the subagent's own identity, collapsing
multiple subagents under one parent into the same compaction
filename. Searching `~/.claude/projects/` to `-maxdepth 4` reaches
the live subagent JSONL and yields the correct composite ID, giving
each subagent its own compaction. The two `case` arms disambiguate
the live layout (`<parent>/subagents/agent-*.jsonl`, parent above)
from the backup layout (`subagents/<parent>/agent-*.jsonl`, parent
below); the backup `find` is kept as a harmless fallback for re-runs
that happen after `--complete`.

### Step 2 — collect the session ID

Read the bash run's output (`BashOutput`). If the loop has exited,
you'll see the UUID; if it hasn't, wait briefly and check again.
Don't proceed past this step without a session ID.

### Step 3 — write the compaction

#### Compaction summary (for a future Claude)

Path: `~/project/compactions/session-<ID>.md`. Structure and content
per `COMPACT.md` (in this skill directory) — progress-report half
on top, `---`, then the `<analysis>` + `<summary>` blocks following
`COMPACT_PROMPT.md` (also in this directory).

If the file already exists, this is a re-run — overwrite with a
cumulative summary covering the whole session through now (the
reader is a future Claude; they only need the latest snapshot).

You don't need to list the user's instructions verbatim — the full
transcript is retrievable from the task runner or the session jsonl
when needed. Capture the *essence* in section 1 of the compaction.

### Step 4 — report what you wrote

Print the path — one for the compaction. Nothing else.
