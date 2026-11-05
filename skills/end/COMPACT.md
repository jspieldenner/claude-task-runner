# COMPACT — save a /compact-style summary + progress report

Output is a single file at `~/project/compactions/session-<ID>.md`,
where `<ID>` is the session identifier provided by the parent `end`
skill (36-char UUID for top-level sessions, 54-char `<parent>-<aid>`
composite for subagents).

The file contains, in order:

1. A session progress report (the conventions are below).
2. A horizontal rule, then a `/compact`-style structured summary
   (`<analysis>` block followed by `<summary>` block), produced by
   following the template in `COMPACT_PROMPT.md` (in this skill directory).

The compaction file is for a future Claude to read — it's how a
later session picks up where this one left off. Optimize for that
reader.

## File layout

```
# Progress report

**Session:** <session-ID>

**What was worked on** — ...
**Key decisions** — ...
...

---

<analysis>
...
</analysis>
<summary>
1. Primary Request and Intent: ...
...
8. Optional Next Step: ...
</summary>
```

Do **not** strip or reformat the `<analysis>` / `<summary>` blocks —
the compaction portion is meant to be the raw model output, so future
sessions can read it back verbatim. The progress-report portion goes
*above* the compaction, separated from it by a `---`.

## Part 1 — the progress report

Lead the file with a `# Progress report` heading, then a
`**Session:** <ID>` line, then a factual debrief. Include whichever
of these apply — omit ones with nothing to say:

- **What was worked on** — changes made, problems solved
- **Key decisions** — architectural choices, tradeoffs
- **What's broken / blocked** — known issues, failing tests,
  regressions
- **Task status changes** — which tasks were run, completed, failed
- **Measurements** — timing data, test results, costs if relevant

Keep it factual and concise. It's the top-of-file briefing — what a
future session reads first before deciding whether to dive into the
long-form compaction below. Don't pre-summarize the compaction; the
progress report stands on its own.

You don't need to list the user's instructions verbatim in either
part — the full transcript is retrievable from the task runner
(`task_runner.py --show <task>`) or the session jsonl. Capture the
*essence* of what the user wanted in section 1 of the compaction and
move on.

## Part 2 — the /compact summary

After the `---` separator, append the raw `<analysis>` + `<summary>`
blocks. The full template lives in
`COMPACT_PROMPT.md` in this skill directory. Read it once and follow it.

## Re-running in the same session

If `~/project/compactions/session-<ID>.md` already exists when this
is invoked, this is a re-run (the user kept working after an earlier
`/end` and is now closing the session again). Read the existing file
and produce an updated version that covers the *whole* session
through now — overwrite, don't append. The reader is a future Claude
who only wants the latest snapshot.

## Differences from the real /compact

- **Tools are allowed** — you must call Write to create the output
  file.
- **Context is not cleared** — the conversation continues as normal
  after the file is written.
- **No wrapping preamble** — the real `/compact` wraps the summary
  into a `This session is being continued...` user message; this
  just saves the raw `<analysis>` + `<summary>` blocks plus the
  progress report to disk.
- **One file, not two** — everything goes into the single compaction
  file; nothing is written to `~/project/progress-reports/`.
