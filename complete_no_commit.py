#!/usr/bin/env python3
"""Run `task_runner.py --complete`, but WITHOUT the git auto-commit.

The user reviews and commits manually — no auto-commit by default — so completing a
task should record its run/result, update status, and advance iterative chains,
but must NOT commit. `post_task_commit` (task_runner.py) is the only auto-commit
in the --complete path; this neuters it and otherwise re-runs --complete verbatim.

Usage: same args as `task_runner.py --complete`, e.g.
    echo 'TASK_RESULT: SUCCESS 4/4' | complete_no_commit.py <task-name>
    complete_no_commit.py <task-name> --output-file /tmp/out.txt
    complete_no_commit.py <task-name> --agent-id <id>
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import task_runner

# The ONLY auto-commit in the --complete path (task_runner.py: complete_task ->
# post_task_commit). Neuter it so result/status/chains are recorded but nothing
# is committed. Its return value is not used by the caller.
task_runner.post_task_commit = lambda *args, **kwargs: None

# Re-dispatch as `--complete <passthrough args>`.
sys.argv = [sys.argv[0], "--complete", *sys.argv[1:]]
task_runner.main()
