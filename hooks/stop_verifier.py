#!/usr/bin/env python3
"""
Stop Verifier Hook - Blocks stop when plan items are incomplete.

Triggers on: Stop event
Purpose: Check plan_state.json for incomplete items and BLOCK stop until done.

Behavior:
- Only counts ACTIONABLE items (skips templates, categories, reference items)
- If actionable items incomplete -> BLOCK stop (continue=False)
- If all actionable items complete -> Allow stop
- If user uses /force-stop -> Allow stop anyway
- If no plan -> Allow stop
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
STOP_ATTEMPTS_FILE = HOOKS_DIR / "stop_attempts.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.stop_verifier_debug.log")
VERIFICATION_LOG = Path("{{PROJECT_DIR}}/progress/plan_verifications.log")

DEFAULT_MAX_STOP_ATTEMPTS = 5


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def log_verification(message: str):
    try:
        VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATION_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_config() -> dict:
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_stop_attempts(session_id: str) -> int:
    try:
        if STOP_ATTEMPTS_FILE.exists():
            data = json.loads(STOP_ATTEMPTS_FILE.read_text())
            return data.get(session_id, 0)
    except Exception:
        pass
    return 0


def increment_stop_attempts(session_id: str) -> int:
    count = get_stop_attempts(session_id) + 1
    try:
        data = {}
        if STOP_ATTEMPTS_FILE.exists():
            try:
                data = json.loads(STOP_ATTEMPTS_FILE.read_text())
            except Exception:
                data = {}
        data[session_id] = count
        data["_last_updated"] = datetime.now().isoformat()
        STOP_ATTEMPTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log_debug(f"Error updating stop attempts: {e}")
    return count


def clear_stop_attempts(session_id: str):
    try:
        if STOP_ATTEMPTS_FILE.exists():
            data = json.loads(STOP_ATTEMPTS_FILE.read_text())
            if session_id in data:
                del data[session_id]
                STOP_ATTEMPTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            with open(PLAN_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def check_force_stop(transcript_path: str) -> bool:
    if not transcript_path or not Path(transcript_path).exists():
        return False

    try:
        with open(transcript_path, "r") as f:
            content = f.read()

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
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    try:
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            log_debug("Plan verification disabled, allowing stop")
            output_hook_response(True)
            sys.exit(0)

        data = json.load(sys.stdin)

        log_debug(f"Stop hook triggered with data: {json.dumps(data, indent=2)[:500]}")

        session_id = data.get("session_id", "")
        transcript_path = data.get("transcript_path", "")

        if check_force_stop(transcript_path):
            log_debug("Force stop requested, allowing stop")
            log_verification(f"Session {session_id}: Force stop - bypassing verification")
            clear_stop_attempts(session_id)
            output_hook_response(True, "Force stop acknowledged. Stopping with incomplete items.")
            sys.exit(0)

        max_stop_attempts = config.get("max_stop_attempts", DEFAULT_MAX_STOP_ATTEMPTS)
        attempts = increment_stop_attempts(session_id)
        if attempts >= max_stop_attempts:
            log_debug(f"Max stop attempts ({max_stop_attempts}) reached, allowing stop")
            log_verification(f"Session {session_id}: Loop prevention - allowed after {attempts} blocked attempts")
            clear_stop_attempts(session_id)
            output_hook_response(True, f"Allowed stop after {attempts} blocked attempts to prevent infinite loop.")
            sys.exit(0)

        plan_state = load_plan_state()

        if not plan_state or not plan_state.get("items"):
            log_debug("No plan state found, allowing stop")
            clear_stop_attempts(session_id)
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
            clear_stop_attempts(session_id)
            output_hook_response(True, f"All {total_items} plan items completed!")
            sys.exit(0)

        log_debug(f"Found {len(incomplete_items)} incomplete items - BLOCKING stop")
        log_verification(f"Session {session_id}: BLOCKED - {len(incomplete_items)}/{total_items} items incomplete")

        items_list = "\n".join([f"  - [ ] {item['task']}" for item in incomplete_items[:10]])
        if len(incomplete_items) > 10:
            items_list += f"\n  ... and {len(incomplete_items) - 10} more"

        next_task = incomplete_items[0]['task'] if incomplete_items else "Unknown"

        system_msg = f"""STOP BLOCKED: {len(incomplete_items)} of {total_items} plan items incomplete.

Remaining items:
{items_list}

NEXT TASK: "{next_task}"

Type "c" to continue, or "force stop" to stop anyway."""

        output_hook_response(False, system_msg)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
