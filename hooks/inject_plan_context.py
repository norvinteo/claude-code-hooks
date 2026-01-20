#!/usr/bin/env python3
"""
Plan Context Injection Hook - Injects plan progress into tool calls.

Triggers on: PreToolUse (Write, Edit, Task)
Purpose: Remind Claude of current plan progress before executing tools.

This helps Claude stay focused on the current task and maintain awareness
of overall plan progress.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path("/Users/norvin/Cursor/bebo-studio/.claude/hooks")
DEBUG_LOG = Path("/Users/norvin/Cursor/bebo-studio/progress/.inject_context_debug.log")

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


def load_config() -> dict:
    """Load config from file."""
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            return json.loads(plan_state_file.read_text())
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def get_plan_summary(plan_state: dict) -> str:
    """Generate a concise plan summary."""
    if not plan_state:
        return None

    items = plan_state.get("items", [])
    if not items:
        return None

    # Count statuses
    completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
    in_progress = sum(1 for i in items if i.get("status") == "in_progress")
    pending = len(items) - completed - in_progress

    # Find current task (first in_progress or first pending)
    current_task = None
    next_task = None

    for item in items:
        status = item.get("status", "pending")
        if status == "in_progress":
            current_task = item.get("task", "Unknown")
            break
        elif status in ["pending", ""] and not current_task:
            current_task = item.get("task", "Unknown")

    # Find next task after current
    found_current = False
    for item in items:
        status = item.get("status", "pending")
        if found_current and status not in ["completed", "done"]:
            next_task = item.get("task", "Unknown")
            break
        if item.get("task") == current_task:
            found_current = True

    # Build summary
    plan_name = plan_state.get("name", "Current Plan")
    progress_pct = (completed / len(items)) * 100 if items else 0

    summary_parts = [
        f"📋 {plan_name}: {completed}/{len(items)} ({progress_pct:.0f}%)"
    ]

    if current_task:
        summary_parts.append(f"⏳ Current: {current_task[:60]}{'...' if len(current_task) > 60 else ''}")

    if next_task and next_task != current_task:
        summary_parts.append(f"⏭️ Next: {next_task[:50]}{'...' if len(next_task) > 50 else ''}")

    return "\n".join(summary_parts)


def get_pending_items_for_sync(plan_state: dict) -> list:
    """Get actionable pending items from plan state for TodoWrite sync."""
    if not plan_state:
        return []

    items = plan_state.get("items", [])
    pending = []
    for item in items:
        status = item.get("status", "pending")
        actionable = item.get("actionable", True)
        if status not in ["completed", "done"] and actionable:
            pending.append({
                "task": item.get("task", ""),
                "status": status,
                "section": item.get("section", "")
            })
    return pending


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


def format_todo_sync_message(pending_items: list) -> str:
    """Format pending plan items as TodoWrite-ready JSON for Claude to use."""
    if not pending_items:
        return ""

    todos = []
    for item in pending_items:
        task = item.get("task", "")
        status = item.get("status", "pending")

        # Normalize status
        if status == "in_progress":
            todo_status = "in_progress"
        else:
            todo_status = "pending"

        todos.append({
            "content": task,
            "status": todo_status,
            "activeForm": task_to_active_form(task)
        })

    msg = "\n\n## 📝 Sync TodoWrite with Plan\n"
    msg += "Use these exact items in your next TodoWrite call:\n\n"
    msg += "```json\n" + json.dumps(todos, indent=2) + "\n```\n"
    msg += "\n**Important:** Use these exact task descriptions to ensure proper plan sync."
    return msg


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Check if plan verification is enabled
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        tool_name = data.get("tool_name", "")
        session_id = data.get("session_id", "default")
        log_debug(f"PreToolUse for {tool_name}")

        # Load plan state with fallback to active plan from other sessions
        if HAS_HELPER:
            plan_state, plan_state_file, is_fallback = load_plan_state_with_fallback(session_id)
            if is_fallback:
                log_debug(f"Using fallback plan from {plan_state.get('session_id') if plan_state else 'unknown'}")
        else:
            plan_state_file, _ = get_session_files(session_id)
            plan_state = load_plan_state(plan_state_file)

        if not plan_state or not plan_state.get("items"):
            output_hook_response(True)
            sys.exit(0)

        # Generate summary
        summary = get_plan_summary(plan_state)

        if summary:
            # Add pending items for TodoWrite sync
            pending_items = get_pending_items_for_sync(plan_state)
            sync_msg = format_todo_sync_message(pending_items)
            full_message = summary + sync_msg

            log_debug(f"Injecting context with {len(pending_items)} pending items")
            output_hook_response(True, full_message)
        else:
            output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
