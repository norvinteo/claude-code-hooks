#!/usr/bin/env python3
"""
Continuation Enforcer Hook - Reinforces continuation after blocked stops.

Triggers on: PrePromptSubmit
Purpose: If previous stop was blocked, remind Claude to continue working.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
STOP_ATTEMPTS_FILE = HOOKS_DIR / "stop_attempts.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.continuation_debug.log")


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            return json.loads(PLAN_STATE_FILE.read_text())
    except Exception:
        pass
    return None


def load_stop_attempts() -> dict:
    try:
        if STOP_ATTEMPTS_FILE.exists():
            return json.loads(STOP_ATTEMPTS_FILE.read_text())
    except Exception:
        pass
    return {}


def get_incomplete_items(plan_state: dict) -> list:
    """Get incomplete ACTIONABLE items from plan state.

    Filters out non-actionable items (templates, categories) so only
    real tasks are counted.
    """
    if not plan_state or not plan_state.get("items"):
        return []
    return [
        item for item in plan_state.get("items", [])
        if item.get("status") not in ["completed", "done"]
        and item.get("actionable") is not False  # Skip templates/categories
    ]


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    try:
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "")
        prompt = data.get("prompt", "").strip().lower()

        if prompt.startswith("/"):
            output_hook_response(True)
            sys.exit(0)

        stop_attempts = load_stop_attempts()
        attempts = stop_attempts.get(session_id, 0)

        if attempts > 0:
            log_debug(f"Session {session_id} has {attempts} blocked stop attempts")

            plan_state = load_plan_state()
            incomplete = get_incomplete_items(plan_state)

            if incomplete:
                next_task = incomplete[0].get("task", "the next task")
                # Count only actionable items for progress
                all_items = plan_state.get("items", [])
                actionable = [i for i in all_items if i.get("actionable") is not False]
                completed = len(actionable) - len(incomplete)
                total = len(actionable)

                reminder = (
                    f"Plan progress: {completed}/{total} complete. "
                    f"Continue with: \"{next_task[:60]}{'...' if len(next_task) > 60 else ''}\""
                )

                log_debug(f"Injecting continuation reminder: {reminder}")
                output_hook_response(True, reminder)
                sys.exit(0)

        output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
