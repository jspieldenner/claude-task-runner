---
name: cyber-false-positive-report
description: Submit a Cyber Block False Positive Report to Anthropic when Claude's cybersecurity safeguard falsely blocks legitimate work (debugging, scientific computing, systems/audio engineering, etc.). Covers gathering the blocked request IDs / evidence and filling out the claude.com Typeform via a browser-automation tool. Use when Claude returns "safety measures … flagged this message for a cybersecurity topic" on benign technical work and the user wants it reported.
---

# Cyber Block False Positive Report

> **Anonymized / shareable version.** All user-, account-, and project-specific
> details have been removed and replaced with `████` placeholders. Wherever you
> see a `████` redaction or a **[ASK THE USER]** marker, you must either already
> know that information from your own context or **ask the user for it before
> proceeding** — do not invent it.

## Requirements

The actual submission (Step 2) is done by **driving a web form**, so you need a
**browser-automation capability** — e.g. a **Playwright MCP server** (the
`browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type`
tool family), or any equivalent means of navigating to a URL, taking
accessibility snapshots, and clicking/typing into elements inside an iframe.
**Without browser automation you cannot complete Step 2.** If you don't have it,
either obtain it (configure a Playwright MCP server) or hand the gathered
evidence to a human to paste into the form manually — Steps 1 (gather evidence)
and 3 (email channel) do not need it.

Optionally helpful but not required:

- A way to retrieve **request IDs and timestamps** from your session
  transcripts/logs for Step 1. If your environment has a session-log tool, use
  it; otherwise, Claude Code keeps raw per-session **JSONL transcripts** under
  `~/.claude/projects/` — if you have read access there you can grep those files
  directly (see Step 1). Failing both, scroll back through the conversation by
  hand — the request IDs are printed inline in each error.
- An **email-sending capability** for the optional parallel channel in Step 3.

Everything else (the form URL, the evidence to collect) is environment-agnostic.

When Claude (typically the largest model) blocks **legitimate, non-security**
work with an error like:

> *API Error: Claude has safety measures that flagged this message for a
> cybersecurity topic. If your work requires this access, you can apply for an
> exemption: https://claude.com/form/cyber-use-case?token=…*

(or the generic *"Claude … is unable to respond to this request, which appears
to violate our Usage Policy"*), and the work is in fact benign, that is a
**false positive**. The trigger is usually **lexical** — everyday engineering
vocabulary such as "trigger / fire / reproduce / exploit a crash", "data race",
"write a reproducer", "segfault", "buffer overflow" — not actual intent.

Report it via the **Cyber Block False Positive Report / CVP Rejection Appeal**
Typeform:

**https://claude.com/form/cyber-block-false-positive-report-cvp-rejection-appeal**

(That URL is given out by Anthropic's support agent and appears in the
`support.claude.com` real-time-cyber-safeguards article. The
`claude.com/form/cyber-use-case` link inside the error message is a *different*
form — the Cyber Verification Program (CVP) application — which is **not** the
place for a false-positive report.)

No login is required to submit the form.

## What you must know or ask before starting — [ASK THE USER]

None of the following can be guessed. Obtain each from your own context, or ask:

- **Organization ID** — redacted here as `████████-████-████-████-████████████`.
  The real value is on the user's account at **https://claude.ai/settings/account**
  or **https://platform.claude.com/settings/organization**. **[ASK THE USER]** if
  you don't have it.
- **Contact name / email** — `████ (████@████)`. **[ASK THE USER]**.
- **What the work actually was** — the legitimate task that got blocked
  (e.g. some debugging, scientific-computing, or systems task). Left entirely to
  the user. **[ASK THE USER]** — describe it in the user's own words; do not
  embellish.
- **Justification** — *why* the block was a false positive, in the user's words.
  **[ASK THE USER]**. (See "Building the argument" for the kinds of evidence that
  are persuasive, but the substance is the user's.)
- **Which submission type(s)** to file — see the decision below. **[ASK THE USER]**
  unless the user has already told you.
- **CVP application date** — only needed if appealing a CVP rejection. **[ASK THE
  USER]**; the date is in the *"We received your Cyber Verification Program
  application!"* confirmation email Anthropic sent.

## Decision: which submission type?

The form's Q3 ("What are you submitting?") offers two checkboxes:
**(A) False Positive Report** and **(B) CVP decision appeal**.

These are independent. A false-positive report (A) says "a specific request was
wrongly blocked." A CVP appeal (B) says "I was rejected from the Cyber
Verification Program and believe I'm eligible." Tick **only what applies**, and
default to whatever the user actually wants — **[ASK THE USER]** if unstated.
Filing A alone is the right choice when the user only wants the misclassification
reported and is **not** seeking expanded/dual-use cyber access. (Ticking B pulls
in the CVP-specific questions Q8/Q9.)

## Step 1 — gather the evidence from the blocked session(s)

The single most important artifact is the **request ID** of each block —
a string like `req_011C…` shown directly in the error message. These are
Anthropic's authoritative server-side handles; they matter more than anything
else on the form.

For each blocked turn, collect:

- The **request ID(s)** and the local **timestamp** of each block.
- The **verbatim error** text (note whether it was the cybersecurity-topic
  variant or the generic Usage-Policy variant).
- The **prompt / request that was blocked** — quote the benign-but-flagged
  wording.
- A **session/conversation identifier**, if your environment has one.

How you retrieve these depends on your environment. Generic options:

- Scroll back through the conversation/transcript and copy the error blocks
  (request IDs are printed inline).
- If you have a session-log tool, use it to extract request IDs and timestamps.
- Otherwise, if you have read access to Claude Code's raw transcripts, grep the
  per-session **JSONL** files directly. They live under `~/.claude/projects/`
  (one subdirectory per working directory, one `<session-uuid>.jsonl` per
  session); grep for `API Error`, `Request ID`, `req_011C`, or `Usage Policy`.
  The filename is the session UUID, which is itself useful supporting evidence.
- Keep a note as each block happens, since the error is shown live.

> The original (non-anonymized) version of this skill used a bespoke
> session-log tool to extract request IDs and exact timestamps. Substitute
> whatever transcript/logging mechanism your environment provides; the form only
> needs the request IDs, timestamps, and error text.

### Building the argument (strong, low-arguable evidence)

When you write the "what were you doing" and "why is this an error" fields, the
most persuasive points are concrete and verifiable:

- **The work is plainly benign** — name the ordinary task and the everyday
  vocabulary that tripped the filter.
- **Spillover** — if, once a session was flagged, *unrelated* benign requests
  (or even the assistant's own housekeeping commands) were then blocked too,
  that shows the classifier latched rather than judged intent.
- **Same-work-clears-on-retry** — if the *identical* task completed with **no**
  cyber flag in a fresh session/attempt, cite it. "Permitted minutes later in a
  new session" is very hard to argue with.

Keep the substance the user's own (**[ASK THE USER]**); the above is just the
shape of a convincing report.

## Step 2 — fill the Typeform with a browser-automation tool

This step needs the browser-automation capability noted in **Requirements**
above. The form is a Typeform embedded in an **iframe** on the page. Mechanics
(written for a Playwright MCP server; adapt to whatever browser automation you
have):

1. Navigate to the form URL.
2. Snapshot the page; click the **"Start"** button (it lives **inside the
   iframe**).
3. Snapshot **scoped to the iframe** thereafter — the surrounding page chrome is
   large and noisy; the iframe-only view is just the form.
4. For each question: fill the field, then click that question's **"OK"**
   (`OK Next question`) button. Typeform reveals questions progressively and
   element references shift, so re-snapshot the iframe between steps.
5. Date questions are three separate **MM / DD / YYYY** textboxes.
6. Single-select (Q1) is a radio click; multi-select (Q3) is checkbox clicks.
7. The final question has a **"Submit"** button instead of "OK".
8. After submitting, confirm the **"Thank you for your submission."** screen.
9. Close the browser as the last action.

### The questions (as of this writing) and how to answer

The form has ~10 questions. It may be re-ordered or re-worded over time ("We
reserve the right to adjust this Form"), so treat this as intent, not a fixed
script — read each question from the live form.

| # | Question | How to answer |
|---|----------|---------------|
| 1 | How are you accessing Claude? | the user's access path (e.g. first-party Claude.ai / Claude Code / API, or a cloud provider) — **[ASK THE USER]** if unclear |
| 2 | Organization ID | `████████-████-████-████-████████████` — **[ASK THE USER]** |
| 3 | What are you submitting? (select all) | per the decision above — **[ASK THE USER]** |
| 4 | When did the False Positive block occur? | date of the (first) block, MM/DD/YYYY |
| 5 | What model was used? | read it from the error string |
| 6 | What were you trying to accomplish? | the user's legitimate task, in their words — **[ASK THE USER]** |
| 7 | Error message you received (may include log_ids / prompts) | verbatim error + **all request IDs** with timestamps and a one-line note of the triggering ask for each |
| 8 | When did you apply for CVP? | **CVP-appeal path only** — the application date from the confirmation email — **[ASK THE USER]** |
| 9 | Why do you believe the decision was made in error? | the user's justification — **[ASK THE USER]**; see "Building the argument" |
| 10 | New information or supporting evidence | session identifiers, any same-work-cleared-on-retry evidence, and any parallel report channel used |

## Step 3 — optional parallel email channel

A structured email to **support@anthropic.com** can complement the form — it
reaches a human queue and lets you attach a readable summary. Expect an
automated reply from the support agent that points back to this same form; that
is normal. Lead with the request IDs and organization ID and **offer**
transcripts rather than pasting them (they may contain private/unpublished
work). Identify yourself appropriately and follow the user's own email
conventions — **[ASK THE USER]** for recipients, CC, and formatting if you are
sending on their behalf.

## Notes

- **Request IDs are the currency.** Everything else is context; the `req_011C…`
  IDs let Anthropic pull the exact request and the classifier decision.
- Don't paste full transcripts into the form or the first email — offer them.
- Keep the tone factual. The least-arguable evidence is the
  **same-work-cleared-on-retry** contrast and any instance of the assistant's
  own benign housekeeping being blocked.
- Everything redacted with `████` or marked **[ASK THE USER]** is intentionally
  left to you to supply from context or by asking — never fabricate it.
