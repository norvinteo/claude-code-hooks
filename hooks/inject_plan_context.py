#!/usr/bin/env python3
"""
Plan Context Injection Hook - Injects plan progress into tool calls.

Triggers on: PreToolUse (Write, Edit, Task)
Purpose: Remind Claude of current plan progress before executing tools.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.inject_context_debug.log")


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
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


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            return json.loads(PLAN_STATE_FILE.read_text())
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def get_plan_summary(plan_state: dict) -> str:
    if not plan_state:
        return None

    items = plan_state.get("items", [])
    if not items:
        return None

    completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
    in_progress = sum(1 for i in items if i.get("status") == "in_progress")

    current_task = None
    next_task = None

    for item in items:
        status = item.get("status", "pending")
        if status == "in_progress":
            current_task = item.get("task", "Unknown")
            break
        elif status in ["pending", ""] and not current_task:
            current_task = item.get("task", "Unknown")

    found_current = False
    for item in items:
        status = item.get("status", "pending")
        if found_current and status not in ["completed", "done"]:
            next_task = item.get("task", "Unknown")
            break
        if item.get("task") == current_task:
            found_current = True

    plan_name = plan_state.get("name", "Current Plan")
    progress_pct = (completed / len(items)) * 100 if items else 0

    summary_parts = [
        f"{plan_name}: {completed}/{len(items)} ({progress_pct:.0f}%)"
    ]

    if current_task:
        summary_parts.append(f"Current: {current_task[:60]}{'...' if len(current_task) > 60 else ''}")

    if next_task and next_task != current_task:
        summary_parts.append(f"Next: {next_task[:50]}{'...' if len(next_task) > 50 else ''}")

    return "\n".join(summary_parts)


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
            output_hook_response(True)
            sys.exit(0)

        data = json.load(sys.stdin)

        tool_name = data.get("tool_name", "")
        log_debug(f"PreToolUse for {tool_name}")

        plan_state = load_plan_state()

        if not plan_state or not plan_state.get("items"):
            output_hook_response(True)
            sys.exit(0)

        summary = get_plan_summary(plan_state)

        if summary:
            log_debug(f"Injecting context: {summary[:100]}...")
            output_hook_response(True, summary)
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
