#!/usr/bin/env python3
"""
Stop Verifier Hook - Blocks stop when plan items are incomplete.

Triggers on: Stop event
Purpose: Check plan_state.json for incomplete items and BLOCK stop until done.

Behavior:
- If plan has incomplete items → BLOCK stop (continue=False)
- If all items complete → Allow stop
- If user uses /force-stop → Allow stop anyway
- If no plan → Allow stop
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent / "progress/.stop_verifier_debug.log"
VERIFICATION_LOG = HOOKS_DIR.parent / "progress/plan_verifications.log"

# Loop prevention settings (can be overridden in config.json)
DEFAULT_MAX_STOP_ATTEMPTS = 5

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


def log_verification(message: str):
    """Log verification results."""
    try:
        VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATION_LOG, "a") as f:
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


def get_stop_attempts(stop_attempts_file: Path) -> int:
    """Track how many times stop was blocked this session."""
    try:
        if stop_attempts_file.exists():
            data = json.loads(stop_attempts_file.read_text())
            return data.get("attempts", 0)
    except Exception:
        pass
    return 0


def increment_stop_attempts(stop_attempts_file: Path) -> int:
    """Increment and return new count."""
    count = get_stop_attempts(stop_attempts_file) + 1
    try:
        stop_attempts_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "attempts": count,
            "_last_updated": datetime.now().isoformat()
        }
        stop_attempts_file.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log_debug(f"Error updating stop attempts: {e}")
    return count


def clear_stop_attempts(stop_attempts_file: Path):
    """Clear stop attempts for a session (called on successful stop)."""
    try:
        if stop_attempts_file.exists():
            stop_attempts_file.unlink()
    except Exception:
        pass


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            with open(plan_state_file, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def check_force_stop(transcript_path: str) -> bool:
    """Check if user explicitly requested force stop."""
    if not transcript_path or not Path(transcript_path).exists():
        return False

    try:
        with open(transcript_path, "r") as f:
            content = f.read()

        # Check for force stop signals in recent messages (last 5000 chars)
        recent_content = content[-5000:] if len(content) > 5000 else content

        force_patterns = [
            r"/force-stop",
            r"/force stop",
            r"force stop",
            r"stop anyway",
            r"ignore incomplete",
            r"skip verification",
            r"let me stop",
        ]

        for pattern in force_patterns:
            if re.search(pattern, recent_content, re.IGNORECASE):
                log_debug(f"Force stop detected: {pattern}")
                return True

    except Exception as e:
        log_debug(f"Error checking force stop: {e}")

    return False


def get_incomplete_items(plan_state: dict) -> list:
    """Get list of incomplete ACTIONABLE items from plan state.

    Only returns items where:
    - status is not "completed" or "done"
    - actionable is not explicitly False (templates/categories are skipped)

    This prevents template/category checkboxes from blocking the stop.
    """
    incomplete = []

    if not plan_state or "items" not in plan_state:
        return incomplete

    for item in plan_state["items"]:
        # Skip non-actionable items (templates, categories, reference items)
        # Items without 'actionable' field default to True (actionable)
        if item.get("actionable") is False:
            continue

        status = item.get("status", "pending")
        if status not in ["completed", "done"]:
            incomplete.append({
                "task": item.get("task", "Unknown task"),
                "status": status,
                "id": item.get("id"),
            })

    return incomplete


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {
        "continue": continue_execution
    }
    if system_message:
        response["systemMessage"] = system_message

    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Check if plan verification is enabled (config file OR env var)
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            log_debug("Plan verification disabled, allowing stop")
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        log_debug(f"Stop hook triggered with data: {json.dumps(data, indent=2)[:500]}")

        session_id = data.get("session_id", "default")
        transcript_path = data.get("transcript_path", "")

        # Get session-scoped file paths
        plan_state_file, stop_attempts_file = get_session_files(session_id)

        # Check for force stop first
        if check_force_stop(transcript_path):
            log_debug("Force stop requested, allowing stop")
            log_verification(f"Session {session_id}: Force stop - bypassing verification")
            clear_stop_attempts(stop_attempts_file)
            output_hook_response(True, "Force stop acknowledged. Stopping with incomplete items.")
            sys.exit(0)

        # Loop prevention: check stop attempts
        max_stop_attempts = config.get("max_stop_attempts", DEFAULT_MAX_STOP_ATTEMPTS)
        attempts = increment_stop_attempts(stop_attempts_file)
        if attempts >= max_stop_attempts:
            log_debug(f"Max stop attempts ({max_stop_attempts}) reached, allowing stop")
            log_verification(f"Session {session_id}: Loop prevention - allowed after {attempts} blocked attempts")
            clear_stop_attempts(stop_attempts_file)
            output_hook_response(True, f"⚠️ Allowed stop after {attempts} blocked attempts to prevent infinite loop.")
            sys.exit(0)

        # Load plan state with fallback to active plan from other sessions
        if HAS_HELPER:
            plan_state, plan_state_file, is_fallback = load_plan_state_with_fallback(session_id)
            if is_fallback:
                log_debug(f"Using fallback plan from {plan_state.get('session_id') if plan_state else 'unknown'}")
        else:
            plan_state = load_plan_state(plan_state_file)

        if not plan_state or not plan_state.get("items"):
            log_debug("No plan state found, allowing stop")
            clear_stop_attempts(stop_attempts_file)
            output_hook_response(True)
            sys.exit(0)

        # Get incomplete items from plan state only (filters out non-actionable items)
        incomplete_items = get_incomplete_items(plan_state)

        # Count total actionable items (for accurate progress reporting)
        all_items = plan_state.get("items", [])
        actionable_items = [i for i in all_items if i.get("actionable") is not False]
        non_actionable_count = len(all_items) - len(actionable_items)
        total_items = len(actionable_items)
        completed_items = total_items - len(incomplete_items)

        if non_actionable_count > 0:
            log_debug(f"Skipping {non_actionable_count} non-actionable items (templates/categories)")

        if not incomplete_items:
            log_debug("All items completed!")
            log_verification(f"Session {session_id}: All {total_items} plan items completed")
            clear_stop_attempts(stop_attempts_file)
            output_hook_response(True, f"✅ All {total_items} plan items completed!")
            sys.exit(0)

        # Items are incomplete - BLOCK the stop
        log_debug(f"Found {len(incomplete_items)} incomplete items - BLOCKING stop")
        log_verification(f"Session {session_id}: BLOCKED - {len(incomplete_items)}/{total_items} items incomplete")

        # Build message with incomplete items
        items_list = "\n".join([f"  - [ ] {item['task']}" for item in incomplete_items[:10]])
        if len(incomplete_items) > 10:
            items_list += f"\n  ... and {len(incomplete_items) - 10} more"

        # Get next task to work on
        next_task = incomplete_items[0]['task'] if incomplete_items else "Unknown"

        # Build a directive message that prompts Claude to continue
        system_msg = f"""🚫 STOP BLOCKED: {len(incomplete_items)} of {total_items} plan items incomplete.

Remaining items:
{items_list}

👉 NEXT TASK: "{next_task}"

Type "c" to continue, or "force stop" to stop anyway."""

        # BLOCK the stop and prompt continuation
        output_hook_response(False, system_msg)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)  # Allow stop on error
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)  # Allow stop on error


if __name__ == "__main__":
    main()
