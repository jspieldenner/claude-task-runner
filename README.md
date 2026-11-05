# Claude Task Runner

A task orchestration system for [Claude Code](https://claude.ai/claude-code) agents.

Manages a database of tasks with dependencies, builds prompts for the Claude
Code Agent tool, records results and costs from subagent logs, and supports
iterative debug/fix loops.

## Features

- **Task management** with dependencies, priorities, and resource groups
- **Multiple agent types** (opus, sonnet, fable)
- **Iterative chains** — automatic test/fix/retest loops with progress detection
- **Structured logging** — subagent logs with tool calls, costs, and timing
- **Auto-commit** — commits agent changes across git repos after successful tasks
- **Continuations** — rerun a task in a fresh session with a continuation note
- **Interactive chat** — drop into an interactive session continuing a task's work
- **Live monitoring** — tail running task output in real-time
- **Backup** — export sessions and push to a backup remote in one command
- **Plan mode redirect** — optionally route Claude's plan mode through the task runner
- **Cost reporting** — track spending by task, session, model, and date

## Setup

**Option A: Scripts and data together** (simplest)

```bash
git clone https://github.com/BrentBaccala/claude-task-runner ~/myproject
cd ~/myproject
```

**Option B: Separate script repo and project data** (recommended if you
want to keep the task runner updatable independently)

```bash
git clone https://github.com/BrentBaccala/claude-task-runner ~/claude-task-runner
mkdir ~/myproject && cd ~/myproject
```

Either way, symlink the scripts into your PATH:

```bash
ln -s ~/claude-task-runner/task_runner.py ~/.local/bin/task_runner.py
ln -s ~/claude-task-runner/format_session.py ~/.local/bin/format_session.py
```

Scripts find project data (`tasks.db`, `prompts/`, `logs/`) in this order:
- `TASK_RUNNER_PROJECT` env variable (if set)
- Current working directory (if it has a non-empty `tasks.db`)
- `~/*/tasks.db` (if exactly one non-empty match)
- Otherwise the current working directory, which is where `init_db.py` creates a new `tasks.db`

For convenience, add to `~/.bashrc`:

```bash
export TASK_RUNNER_PROJECT=~/myproject
```

Then start a Claude Code session in your project directory and tell it to
create tasks:

> "Create a task to build the project and run the test suite"

> "Create a task to review the code in src/ for security issues"

Claude reads `CLAUDE.md` and knows how to use the task runner — it will
initialize the database, write prompts, and create tasks. You direct,
Claude executes.

To monitor and view results from the command line:

```bash
task_runner.py --tail my-task     # live output while running
task_runner.py --show my-task     # formatted results
task_runner.py --show my-task -v  # with tool calls
```

`--show` verbosity levels:

| Flag | Shows |
|------|-------|
| (default) | Assistant text only |
| `-v` | + tool invocations (which tools were called) |
| `-vv` | + tool output (results from each tool) |
| `-vvv` | + full tool input content (Write bodies, Edit strings) |

## Files

| File | Purpose |
|------|---------|
| `task_runner.py` | Main script — manages tasks, builds Agent tool prompts, records results, auto-commits |
| `format_session.py` | Format/browse Claude Code session logs |
| `export_sessions.py` | Export session files and memory into the project directory |
| `init_db.py` | Database schema (creates `tasks.db`) |
| `agent-settings.json` | Hook settings from the old subprocess runner. Not loaded by current code |
| `cost_report.py` | Cost analysis by task, session, model, and date |
| `turn_chart.py` | Visual turn/duration chart for task run history |

## Task Lifecycle

```
pending → running → completed
                  → failed
                  → interrupted (Ctrl+C or --kill)
                  → timeout
                  → max_turns
                  → usage_limit

hold ↔ pending (via --hold / --unhold)
failed/interrupted/timeout/max_turns/usage_limit/completed → pending (via --continue)
any non-running → pending (via --reset)
```

## Commands

```bash
# Viewing
task_runner.py --list                   # All tasks with status
task_runner.py --history                # Tasks by last run time, with cost
task_runner.py --summary                # Aggregate stats by agent type
task_runner.py --pending                # Tasks ready for --prepare
task_runner.py --show NAME              # Task output (all run headers, last run detail)
task_runner.py --show NAME -v           # + tool call summaries
task_runner.py --show NAME -vv          # + tool output
task_runner.py --show NAME --all        # Full detail for every run

# Cost and analytics
cost_report.py                         # Summary + cost by task and session
cost_report.py --by-model              # Cost breakdown by model
cost_report.py --by-date               # Daily cost breakdown
cost_report.py --detail                # Per-run detail with token counts
cost_report.py --task NAME             # Cost for a specific task
turn_chart.py                          # Visual chart of turns per run

# Running (via the Agent tool, see CLAUDE.md)
task_runner.py --prepare NAME           # Create run record, print prompt
task_runner.py --set-agent-id NAME ID   # Record agent ID, mark running
task_runner.py --complete NAME          # Record result, auto-commit, chains
task_runner.py --continue NAME          # Set to pending with a continuation note for the next --prepare
task_runner.py --continue NAME --prompt "Try X"
task_runner.py --chat NAME              # Interactive session on a task
task_runner.py --tail NAME              # Tail live output

# Managing
task_runner.py --reset NAME             # Reset to pending
task_runner.py --hold NAME / --unhold NAME
task_runner.py --kill NAME              # Mark a running task as interrupted (does not stop the agent)
task_runner.py --sync NAME              # Update status from chat continuation
task_runner.py --backup                 # Export sessions, commit, push

# Creating
task_runner.py --create NAME --agent TYPE
task_runner.py --create NAME --agent TYPE --depends dep1,dep2
task_runner.py --create NAME --agent TYPE --priority 20
```

## Iterative Chains

Set up automatic test/fix loops:

```bash
# Test task: activates fix task on partial failure
task_runner.py --create my-test --agent opus \
  --on-partial-failure my-fix --iterate-limit 5

# Fix task: re-runs test after success
task_runner.py --create my-fix --agent opus \
  --rerun-after my-test --hold-on-create
```

The loop continues as long as the test result improves (e.g., `FAILURE 10/11` → `FAILURE 11/11`).

## TASK_RESULT Protocol

Agents must write a result marker as the last line of their response:

```
TASK_RESULT: SUCCESS
TASK_RESULT: FAILURE
TASK_RESULT: SUCCESS 184/184
TASK_RESULT: FAILURE 10/11
```

The task runner parses this to determine success/failure and track progress.

## Agent Types

The default agent types are `opus`, `sonnet`, and `fable`. Any string can be
used as an agent type. Unknown types use the opus model. To add custom types,
edit the `AGENT_MODELS` dict near the top of `task_runner.py`.

## Plan Mode Redirect

By default, when Claude proposes a plan it enters "plan mode" which clears
context and implements immediately. You can redirect this to use the task
runner instead, so plans become tasks that can be reviewed, edited, and run
on demand.

Ask Claude to set this up:

> "Redirect plan mode to use the task runner instead of clearing context"

Or add the hook manually to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "EnterPlanMode",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'BLOCKED: Do not use plan mode. Instead, write the plan to prompts/NAME and run: task_runner.py --create NAME --agent TYPE' >&2; exit 2"
          }
        ]
      }
    ]
  }
}
```

## Requirements

- [Claude Code](https://claude.ai/claude-code) CLI installed (`~/.local/bin/claude`)
- Python 3.10+ with `psutil` (used by `--send`)
- SQLite3

## License

MIT
