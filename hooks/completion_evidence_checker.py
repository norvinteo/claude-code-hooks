#!/usr/bin/env python3
"""
Completion Evidence Checker Hook - Verifies work before allowing task completion.

Triggers on: PreToolUse with matcher "TodoWrite"
Purpose: Before allowing a todo to be marked complete, verify evidence of actual work:
         - Check if relevant files were modified (git diff)
         - Quick lint/type check on changed files (optional)
         - Warn if no files changed but trying to mark complete

This prevents Claude from:
1. Marking tasks complete without doing the work
2. Assuming completion without verification
3. Forgetting to actually implement before marking done

Config options in config.json:
- evidence_checker_enabled: true/false - Enable this hook
- require_file_changes: true/false - Block completion if no files changed
- quick_validate_changes: true/false - Run quick lint on changed files
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration - use relative paths for portability
HOOKS_DIR = Path(__file__).parent
PROJECT_DIR = HOOKS_DIR.parent.parent  # .claude/hooks -> .claude -> project root
DEBUG_LOG = PROJECT_DIR / "progress/.evidence_checker_debug.log"

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


def get_recent_file_changes() -> list:
    """Get list of recently modified files using git.

    Returns files that have been modified in the working tree
    (both staged and unstaged changes).
    """
    try:
        # Get both staged and unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            return files

        # Also check for staged changes (in case nothing committed)
        result_staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result_staged.returncode == 0 and result_staged.stdout.strip():
            files = [f.strip() for f in result_staged.stdout.strip().split("\n") if f.strip()]
            return files

    except subprocess.TimeoutExpired:
        log_debug("Git diff timed out")
    except Exception as e:
        log_debug(f"Error getting file changes: {e}")

    return []


def get_session_file_changes(session_id: str) -> list:
    """Get file changes tracked during this session.

    Uses a session-specific file to track what files have been
    modified during the current Claude session.
    """
    sessions_dir = HOOKS_DIR / "sessions"
    changes_file = sessions_dir / f"{session_id}_file_changes.json"

    try:
        if changes_file.exists():
            data = json.loads(changes_file.read_text())
            return data.get("files", [])
    except Exception:
        pass
    return []


def quick_validate_files(files: list) -> tuple:
    """Run quick TypeScript check on specific files.

    Returns:
        tuple: (success: bool, errors: list)
    """
    if not files:
        return True, []

    # Filter to only TypeScript/JavaScript files
    ts_files = [f for f in files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]

    if not ts_files:
        return True, []

    # Take only first 10 files to avoid timeout
    ts_files = ts_files[:10]

    try:
        # Quick type check using tsc
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--pretty", "false"] + ts_files,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return True, []

        # Extract error messages
        errors = []
        for line in result.stdout.split("\n"):
            if "error TS" in line:
                errors.append(line[:150])
                if len(errors) >= 5:
                    break

        return False, errors

    except subprocess.TimeoutExpired:
        log_debug("Quick validate timed out")
        return True, []  # Don't block on timeout
    except Exception as e:
        log_debug(f"Error in quick validate: {e}")
        return True, []  # Don't block on error


def get_pending_plan_items(plan_state: dict) -> list:
    """Get pending items from plan state."""
    if not plan_state or not plan_state.get("items"):
        return []

    return [
        item for item in plan_state.get("items", [])
        if item.get("status") not in ["completed", "done"]
        and item.get("actionable") is not False
    ]


def detect_completion_attempts(todos: list, plan_items: list) -> list:
    """Detect which todos are being marked as complete.

    Compares incoming TodoWrite items against plan items to find
    items being marked as completed.
    """
    completing = []

    for todo in todos:
        if todo.get("status") == "completed":
            content = todo.get("content", "").lower()

            # Check if this matches a pending plan item
            for item in plan_items:
                task = item.get("task", "").lower()
                # Simple substring matching
                if task in content or content in task or \
                   any(word in content for word in task.split()[:3]):
                    completing.append({
                        "todo_content": todo.get("content"),
                        "plan_task": item.get("task"),
                        "plan_id": item.get("id")
                    })
                    break

    return completing


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Check if evidence checker is enabled
        config = load_config()

        # Check both plan_verification and evidence_checker_enabled
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)
        evidence_enabled = config.get("evidence_checker_enabled", True)  # Default enabled

        if not ((env_enabled or config_enabled) and evidence_enabled):
            log_debug("Evidence checker disabled")
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "default")
        tool_input = data.get("tool_input", {})
        todos = tool_input.get("todos", [])

        log_debug(f"Session {session_id}: Evidence checker triggered with {len(todos)} todos")

        if not todos:
            output_hook_response(True)
            sys.exit(0)

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

        # Get pending plan items
        pending_items = get_pending_plan_items(plan_state)

        if not pending_items:
            output_hook_response(True)
            sys.exit(0)

        # Detect completion attempts
        completing = detect_completion_attempts(todos, pending_items)

        if not completing:
            # No plan items being marked complete
            output_hook_response(True)
            sys.exit(0)

        log_debug(f"Detected {len(completing)} items being marked complete")

        # Check for evidence: file changes
        require_changes = config.get("require_file_changes", False)  # Default: warn only
        quick_validate = config.get("quick_validate_changes", False)  # Default: skip validation

        git_changes = get_recent_file_changes()
        session_changes = get_session_file_changes(session_id)
        all_changes = list(set(git_changes + session_changes))

        log_debug(f"Found {len(all_changes)} file changes")

        # Build response message
        messages = []
        should_block = False

        if not all_changes:
            # No file changes detected
            tasks_text = "\n".join([f"  - {c['todo_content']}" for c in completing])

            if require_changes:
                # Block the completion
                should_block = True
                messages.append(
                    f"⚠️ **COMPLETION BLOCKED**: No file changes detected.\n\n"
                    f"You're marking these tasks as complete:\n{tasks_text}\n\n"
                    f"**Verify that you've actually implemented these changes.**\n"
                    f"If this is a non-code task, add `require_file_changes: false` to config."
                )
            else:
                # Just warn
                messages.append(
                    f"⚠️ **Note**: Marking tasks complete but no file changes detected.\n"
                    f"Tasks: {', '.join([c['todo_content'][:40] for c in completing])}\n\n"
                    f"Ensure the work was actually completed."
                )
        else:
            # File changes detected - optionally validate
            if quick_validate:
                success, errors = quick_validate_files(all_changes)

                if not success and errors:
                    error_text = "\n".join([f"  - {e}" for e in errors])
                    messages.append(
                        f"⚠️ **Validation issues** in changed files:\n{error_text}\n\n"
                        f"Consider fixing these before marking tasks complete."
                    )

        # Output response
        if should_block:
            output_hook_response(False, "\n\n".join(messages))
        elif messages:
            output_hook_response(True, "\n\n".join(messages))
        else:
            log_debug("Evidence check passed")
            output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)  # Don't block on errors


if __name__ == "__main__":
    main()
