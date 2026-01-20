#!/usr/bin/env python3
"""
Continuation Enforcer Hook - Reinforces continuation after blocked stops.

Triggers on: PrePromptSubmit
Purpose: If previous stop was blocked, remind Claude to continue working.

This works with stop_verifier.py to create a more robust continuation loop.

Note: Uses @ prefix for commands to avoid conflicts with Claude Code's skill system (/).
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent / "progress/.continuation_debug.log"


def get_session_files(session_id: str) -> tuple:
    """Get session-scoped file paths."""
    sessions_dir = HOOKS_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    plan_state_file = sessions_dir / f"{session_id}_plan_state.json"
    stop_attempts_file = sessions_dir / f"{session_id}_stop_attempts.json"

    return plan_state_file, stop_attempts_file


def log_debug(message: str):
    """Log debug message to file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            return json.loads(plan_state_file.read_text())
    except Exception:
        pass
    return None


def load_stop_attempts(stop_attempts_file: Path) -> int:
    """Load stop attempts count for the session."""
    try:
        if stop_attempts_file.exists():
            data = json.loads(stop_attempts_file.read_text())
            return data.get("attempts", 0)
    except Exception:
        pass
    return 0


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
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Read JSON input from stdin
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "")
        prompt = data.get("prompt", "").strip().lower()

        # Don't interfere with explicit commands (@ prefix for plan commands)
        if prompt.startswith("@"):
            output_hook_response(True)
            sys.exit(0)

        # Get session-scoped file paths
        plan_state_file, stop_attempts_file = get_session_files(session_id)

        # Check if there were recent blocked stop attempts
        attempts = load_stop_attempts(stop_attempts_file)

        if attempts > 0:
            log_debug(f"Session {session_id} has {attempts} blocked stop attempts")

            # Load plan state to get next task
            plan_state = load_plan_state(plan_state_file)
            incomplete = get_incomplete_items(plan_state)

            if incomplete:
                next_task = incomplete[0].get("task", "the next task")
                # Count only actionable items for progress
                all_items = plan_state.get("items", [])
                actionable = [i for i in all_items if i.get("actionable") is not False]
                completed = len(actionable) - len(incomplete)
                total = len(actionable)

                # Inject a reminder
                reminder = (
                    f"\ud83d\udccb Plan progress: {completed}/{total} complete. "
                    f"Continue with: \"{next_task[:60]}{'...' if len(next_task) > 60 else ''}\""
                )

                log_debug(f"Injecting continuation reminder: {reminder}")
                output_hook_response(True, reminder)
                sys.exit(0)

        # No blocked attempts or no incomplete items
        output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
