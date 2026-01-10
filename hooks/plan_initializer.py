#!/usr/bin/env python3
"""
Plan Initializer Hook - Detects plan commands and initializes plan state.

Triggers on: PrePromptSubmit
Purpose: Detect /plan, /newplan, /clearplan commands and manage plan state.

Commands:
- /plan <name>     - Initialize a new plan with given name
- /newplan <name>  - Same as /plan
- /clearplan       - Clear current plan state
- /showplan        - Show current plan status
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent / "progress/.plan_init_debug.log"


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
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def save_plan_state(state: dict, plan_state_file: Path) -> bool:
    """Save plan state to file."""
    try:
        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()
        plan_state_file.write_text(json.dumps(state, indent=2))
        log_debug(f"Saved plan state to {plan_state_file.name}: {state.get('name', 'Unknown')}")
        return True
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")
        return False


def clear_plan_state(plan_state_file: Path) -> bool:
    """Clear plan state file."""
    try:
        if plan_state_file.exists():
            plan_state_file.unlink()
        log_debug(f"Cleared plan state: {plan_state_file.name}")
        return True
    except Exception as e:
        log_debug(f"Error clearing plan state: {e}")
        return False


def get_plan_summary(plan_state: dict) -> str:
    """Generate plan summary."""
    if not plan_state:
        return "No active plan for this session."

    items = plan_state.get("items", [])
    name = plan_state.get("name", "Unnamed Plan")

    if not items:
        return f"📋 Plan: {name}\nNo items yet. Use TodoWrite to add tasks."

    completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
    total = len(items)
    progress_pct = (completed / total) * 100 if total else 0

    summary = [
        f"📋 Plan: {name}",
        f"Progress: {completed}/{total} ({progress_pct:.0f}%)",
        "",
        "Items:"
    ]

    for i, item in enumerate(items, 1):
        status = item.get("status", "pending")
        task = item.get("task", "Unknown")
        if status in ["completed", "done"]:
            summary.append(f"  ✅ {i}. {task}")
        elif status == "in_progress":
            summary.append(f"  🔄 {i}. {task}")
        else:
            summary.append(f"  ⬜ {i}. {task}")

    return "\n".join(summary)


def output_hook_response(continue_execution: bool = True, message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if message:
        response["message"] = message  # Use 'message' to show to user (not 'systemMessage')
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Read JSON input from stdin
        data = json.load(sys.stdin)

        prompt = data.get("prompt", "").strip()
        session_id = data.get("session_id", "default")

        # Get session-scoped file paths
        plan_state_file, _ = get_session_files(session_id)

        log_debug(f"Session {session_id}: Received prompt: {prompt[:100]}...")

        # Check for plan commands
        prompt_lower = prompt.lower()

        # /plan <name> or /newplan <name>
        plan_match = re.match(r'^/(?:new)?plan\s+(.+)$', prompt, re.IGNORECASE)
        if plan_match:
            plan_name = plan_match.group(1).strip()
            log_debug(f"Session {session_id}: Initializing plan: {plan_name}")

            plan_state = {
                "session_id": session_id,
                "plan_source": "command",
                "plan_file": None,
                "name": plan_name,
                "description": "",
                "items": [],
                "verification": {},
                "format": "command",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            if save_plan_state(plan_state, plan_state_file):
                output_hook_response(
                    True,
                    message=f"📋 New plan initialized: **{plan_name}**\n\n"
                    f"Use TodoWrite to add tasks that will be tracked.\n"
                    f"Stop will be blocked until all tasks are completed.\n"
                    f"Use `/clearplan` to remove the plan or `/showplan` to see status."
                )
            else:
                output_hook_response(True, message="❌ Failed to initialize plan.")
            sys.exit(0)

        # /clearplan
        if prompt_lower in ["/clearplan", "/clear-plan", "/cleartasks"]:
            log_debug(f"Session {session_id}: Clearing plan")
            if clear_plan_state(plan_state_file):
                output_hook_response(True, message="🗑️ Plan cleared. Stop verification disabled.")
            else:
                output_hook_response(True, message="❌ Failed to clear plan.")
            sys.exit(0)

        # /showplan
        if prompt_lower in ["/showplan", "/show-plan", "/planstatus", "/plan-status"]:
            log_debug(f"Session {session_id}: Showing plan status")
            plan_state = load_plan_state(plan_state_file)
            summary = get_plan_summary(plan_state)
            output_hook_response(True, message=summary)
            sys.exit(0)

        # No plan command - just continue normally
        output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
