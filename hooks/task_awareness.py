#!/usr/bin/env python3
"""
Task Awareness Hook - Reminds Claude of current task before file edits.

Triggers on: PreToolUse with matcher "Write|Edit"
Purpose: Before Claude edits a file, check if the current task relates to this file.
         If not, inject a reminder of what the current task is.

This prevents Claude from:
1. Drifting to unrelated files mid-task
2. Forgetting the current objective while editing
3. Making unnecessary changes outside the task scope

Light-touch approach:
- Only injects a brief reminder, doesn't block
- Helps maintain focus without being intrusive
- Only activates when there's a meaningful mismatch

Config options in config.json:
- task_awareness_enabled: true/false - Enable this hook
- task_awareness_strict: true/false - Show reminder for all edits, not just mismatches
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# Configuration - use relative paths for portability
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent.parent / "progress/.task_awareness_debug.log"

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
            return json.loads(config_file.read_text())
    except Exception:
        pass
    return {}


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            return json.loads(plan_state_file.read_text())
    except Exception:
        pass
    return None


def get_current_task(plan_state: dict) -> dict:
    """Get the current task (first in_progress or first pending).

    Returns dict with task info or None.
    """
    if not plan_state or not plan_state.get("items"):
        return None

    items = plan_state.get("items", [])

    # First look for in_progress
    for item in items:
        if item.get("status") == "in_progress" and item.get("actionable") is not False:
            return item

    # Then first pending
    for item in items:
        if item.get("status") not in ["completed", "done"] and item.get("actionable") is not False:
            return item

    return None


def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text."""
    # Normalize: lowercase, replace punctuation with spaces
    normalized = re.sub(r'[^\w\s]', ' ', text.lower())
    words = normalized.split()

    # Stop words to filter
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "this", "that", "these", "those", "it", "its", "and", "but", "or",
        "fix", "add", "create", "update", "implement", "modify", "change",
        "file", "files", "code", "function", "component", "page", "hook",
    }

    return {w for w in words if w not in stop_words and len(w) > 2}


def extract_file_path_keywords(file_path: str) -> set:
    """Extract keywords from a file path."""
    # Get filename and parent directories
    parts = file_path.replace("\\", "/").split("/")

    keywords = set()
    for part in parts[-3:]:  # Last 3 path components
        # Remove extension
        name = part.rsplit(".", 1)[0] if "." in part else part
        # Split camelCase and snake_case
        words = re.sub(r'([a-z])([A-Z])', r'\1 \2', name).lower()
        words = words.replace("_", " ").replace("-", " ")
        keywords.update(w for w in words.split() if len(w) > 2)

    return keywords


def task_relates_to_file(task: str, file_path: str) -> bool:
    """Check if a task description relates to a file being edited.

    Uses keyword overlap to determine relevance.
    """
    task_keywords = extract_keywords(task)
    file_keywords = extract_file_path_keywords(file_path)

    # Check for any overlap
    overlap = task_keywords & file_keywords

    if overlap:
        log_debug(f"Task-file match: {overlap}")
        return True

    # Also check if file path contains task keywords directly
    file_path_lower = file_path.lower()
    for keyword in task_keywords:
        if keyword in file_path_lower:
            log_debug(f"Task keyword '{keyword}' found in file path")
            return True

    return False


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Check if task awareness is enabled
        config = load_config()

        # Check both plan_verification and task_awareness_enabled
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)
        awareness_enabled = config.get("task_awareness_enabled", True)  # Default enabled

        if not ((env_enabled or config_enabled) and awareness_enabled):
            log_debug("Task awareness disabled")
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "default")
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        # Get file path from tool input
        file_path = tool_input.get("file_path", "")

        if not file_path:
            output_hook_response(True)
            sys.exit(0)

        log_debug(f"Session {session_id}: Task awareness for {tool_name} on {file_path}")

        # Load plan state
        if HAS_HELPER:
            plan_state, plan_state_file, is_fallback = load_plan_state_with_fallback(session_id)
        else:
            plan_state_file, _ = get_session_files(session_id)
            plan_state = load_plan_state(plan_state_file)

        # If no plan, don't interfere
        if not plan_state or not plan_state.get("items"):
            output_hook_response(True)
            sys.exit(0)

        # Get current task
        current_task = get_current_task(plan_state)

        if not current_task:
            output_hook_response(True)
            sys.exit(0)

        task_text = current_task.get("task", "")
        plan_name = plan_state.get("name", "Current Plan")

        # Check if task relates to file
        strict_mode = config.get("task_awareness_strict", False)
        is_related = task_relates_to_file(task_text, file_path)

        if is_related and not strict_mode:
            # Task relates to file, no need to remind
            log_debug(f"Task relates to file, no reminder needed")
            output_hook_response(True)
            sys.exit(0)

        # Inject a brief reminder
        filename = Path(file_path).name

        if is_related:
            # Strict mode: show task context even for related files
            reminder = (
                f"📋 **{plan_name}** | Current task: {task_text[:60]}{'...' if len(task_text) > 60 else ''}"
            )
        else:
            # Not clearly related - more prominent reminder
            reminder = (
                f"📋 **Current task**: {task_text}\n\n"
                f"You're editing `{filename}`. Ensure this edit addresses the task above."
            )
            log_debug(f"Injecting task reminder for unrelated file edit")

        output_hook_response(True, reminder)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
