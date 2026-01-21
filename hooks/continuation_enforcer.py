#!/usr/bin/env python3
"""
Continuation Enforcer Hook - Reinforces continuation after blocked stops.

Triggers on: PrePromptSubmit
Purpose: If previous stop was blocked OR session resumed with active plan,
         inject FULL plan context so Claude knows exactly where to continue.

This works with stop_verifier.py to create a more robust continuation loop.

Enhanced to provide:
- Full plan context with all tasks listed
- Clear progress indicator
- Last completed task for context
- TodoWrite-ready JSON for immediate sync
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Configuration - use relative paths for portability
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent.parent / "progress/.continuation_debug.log"

# Import shared helper for cross-session plan tracking
try:
    from plan_session_helper import load_plan_state_with_fallback
    HAS_HELPER = True
except ImportError:
    HAS_HELPER = False


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


def get_completed_items(plan_state: dict) -> list:
    """Get completed ACTIONABLE items from plan state."""
    if not plan_state or not plan_state.get("items"):
        return []
    return [
        item for item in plan_state.get("items", [])
        if item.get("status") in ["completed", "done"]
        and item.get("actionable") is not False
    ]


def task_to_active_form(task: str) -> str:
    """Convert task description to present participle (activeForm) for TodoWrite."""
    if not task:
        return task

    verb_mappings = {
        "fix": "Fixing", "add": "Adding", "create": "Creating", "update": "Updating",
        "run": "Running", "test": "Testing", "deploy": "Deploying", "implement": "Implementing",
        "modify": "Modifying", "remove": "Removing", "delete": "Deleting", "refactor": "Refactoring",
        "write": "Writing", "read": "Reading", "build": "Building", "configure": "Configuring",
        "setup": "Setting up", "set up": "Setting up", "check": "Checking", "verify": "Verifying",
        "review": "Reviewing", "analyze": "Analyzing", "debug": "Debugging", "optimize": "Optimizing",
        "install": "Installing", "migrate": "Migrating", "integrate": "Integrating",
    }

    words = task.split()
    if not words:
        return task

    first_word = words[0].lower()
    if first_word.endswith("ing"):
        return task.capitalize() if task[0].islower() else task

    if first_word in verb_mappings:
        words[0] = verb_mappings[first_word]
        return " ".join(words)

    return task.capitalize() if task[0].islower() else task


def format_full_plan_context(plan_state: dict, incomplete: list) -> str:
    """Generate FULL plan context for Claude with all details.

    This provides everything Claude needs to continue:
    - Plan name and overall progress
    - What's completed (for context)
    - What remains (with START HERE marker)
    - Last activity timestamp
    - TodoWrite-ready JSON
    """
    plan_name = plan_state.get("name", "Current Plan")
    all_items = plan_state.get("items", [])
    actionable = [i for i in all_items if i.get("actionable") is not False]
    completed_items = get_completed_items(plan_state)

    total = len(actionable)
    completed = len(completed_items)

    # Build the full context message
    msg_parts = [
        f"📋 ACTIVE PLAN: {plan_name}",
        f"Progress: {completed}/{total} tasks complete",
        ""
    ]

    # Show completed tasks (if any)
    if completed_items:
        msg_parts.append("✅ COMPLETED:")
        for item in completed_items:
            task = item.get("task", "Unknown")
            msg_parts.append(f"- {task}")
        msg_parts.append("")

    # Show remaining tasks with START HERE marker
    if incomplete:
        msg_parts.append("⏳ REMAINING (your current work):")
        for i, item in enumerate(incomplete):
            task = item.get("task", "Unknown")
            status = item.get("status", "pending")
            status_icon = "🔄" if status == "in_progress" else "[ ]"
            start_marker = " ← START HERE" if i == 0 else ""
            msg_parts.append(f"{i+1}. {status_icon} {task}{start_marker}")
        msg_parts.append("")

    # Add last activity timestamp if available
    updated_at = plan_state.get("updated_at")
    if updated_at:
        try:
            # Parse and format timestamp
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            msg_parts.append(f"Last activity: {dt.strftime('%Y-%m-%d %H:%M')}")
        except Exception:
            pass

    # Add critical instruction
    msg_parts.extend([
        "",
        "DO NOT attempt to stop until all tasks are complete.",
        ""
    ])

    # Add TodoWrite-ready JSON for immediate sync
    todos = []
    for item in incomplete:
        task = item.get("task", "")
        status = item.get("status", "pending")
        todos.append({
            "content": task,
            "status": "in_progress" if status == "in_progress" else "pending",
            "activeForm": task_to_active_form(task)
        })

    msg_parts.extend([
        "---",
        "## 📝 Initialize TodoWrite",
        "Call `TodoWrite` with these items to track progress:",
        "",
        "```json",
        json.dumps(todos, indent=2),
        "```"
    ])

    return "\n".join(msg_parts)


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

        # Don't interfere with explicit commands
        if prompt.startswith("/") or prompt.startswith("@"):
            output_hook_response(True)
            sys.exit(0)

        # Get session-scoped file paths
        plan_state_file, stop_attempts_file = get_session_files(session_id)

        # Check if there were recent blocked stop attempts
        attempts = load_stop_attempts(stop_attempts_file)

        # Load plan state with fallback to active plan from other sessions
        is_fallback = False
        if HAS_HELPER:
            plan_state, plan_state_file, is_fallback = load_plan_state_with_fallback(session_id)
            if is_fallback:
                log_debug(f"Session {session_id}: Using fallback plan from {plan_state.get('session_id') if plan_state else 'unknown'}")
        else:
            plan_state = load_plan_state(plan_state_file)

        # Check if there's an active plan with incomplete items
        incomplete = get_incomplete_items(plan_state) if plan_state else []

        if not incomplete:
            # No active plan or all complete
            output_hook_response(True)
            sys.exit(0)

        # Determine if we need to inject full context
        # Inject full context if:
        # 1. Stop was blocked (attempts > 0)
        # 2. This is a session resume (is_fallback = True)
        # 3. Plan has items but no TodoWrite has been called yet (first prompt of session)

        inject_full_context = attempts > 0

        if HAS_HELPER and is_fallback:
            # Session resumed with active plan from another session
            inject_full_context = True
            log_debug(f"Session {session_id}: Session resume detected, injecting full context")

        if inject_full_context:
            log_debug(f"Session {session_id} has {attempts} blocked stop attempts, {len(incomplete)} incomplete items")

            # Generate FULL plan context
            full_context = format_full_plan_context(plan_state, incomplete)

            log_debug(f"Injecting full plan context ({len(incomplete)} remaining tasks)")
            output_hook_response(True, full_context)
            sys.exit(0)
        else:
            # Just provide a brief reminder of current task
            next_task = incomplete[0].get("task", "the next task")
            all_items = plan_state.get("items", [])
            actionable = [i for i in all_items if i.get("actionable") is not False]
            completed = len(actionable) - len(incomplete)
            total = len(actionable)

            brief_reminder = (
                f"📋 Plan: {plan_state.get('name', 'Active')}: {completed}/{total} complete. "
                f"Current: \"{next_task[:50]}{'...' if len(next_task) > 50 else ''}\""
            )
            log_debug(f"Injecting brief reminder: {brief_reminder[:100]}")
            output_hook_response(True, brief_reminder)
            sys.exit(0)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
