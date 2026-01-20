#!/usr/bin/env python3
"""
Plan Initializer Hook - Detects plan commands and initializes plan state.

Triggers on: PrePromptSubmit
Purpose: Detect @plan, @newplan, @clearplan commands and manage plan state.

Commands:
- @plan <name>         - Initialize a new plan with given name
- @newplan <name>      - Same as @plan
- @clearplan           - Clear current plan state
- @showplan            - Show current plan status
- @continue            - List available session continuations
- @continue <id>       - Continue from a previous session (use first 8 chars of session ID)
- @continuations       - Alias for @continue

Note: Uses @ prefix to avoid conflicts with Claude Code's skill system (/) and bash history (!).
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path("/Users/norvin/Cursor/bebo-studio/.claude/hooks")
CONTINUATIONS_DIR = Path("/Users/norvin/Cursor/bebo-studio/.claude/continuations")
DEBUG_LOG = Path("/Users/norvin/Cursor/bebo-studio/progress/.plan_init_debug.log")
PROJECT_ROOT = Path("/Users/norvin/Cursor/bebo-studio")
PROJECT_NAME = PROJECT_ROOT.name  # "bebo-studio"

# Import shared helper
try:
    from plan_session_helper import get_session_files, save_active_plan, clear_active_plan
except ImportError:
    # Fallback if helper not available
    def get_session_files(session_id: str) -> tuple:
        """Get session-scoped file paths."""
        sessions_dir = HOOKS_DIR / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        plan_state_file = sessions_dir / f"{session_id}_plan_state.json"
        stop_attempts_file = sessions_dir / f"{session_id}_stop_attempts.json"
        return plan_state_file, stop_attempts_file

    def save_active_plan(session_id, plan_file=None, name=None):
        pass

    def clear_active_plan():
        pass


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
    """Save plan state to file and update active plan reference."""
    try:
        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()
        plan_state_file.write_text(json.dumps(state, indent=2))

        # Update active plan reference
        save_active_plan(
            session_id=state.get("session_id"),
            plan_file=state.get("plan_file"),
            name=state.get("name")
        )

        log_debug(f"Saved plan state to {plan_state_file.name}: {state.get('name', 'Unknown')}")
        return True
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")
        return False


def clear_plan_state(plan_state_file: Path) -> bool:
    """Clear plan state file and active plan reference."""
    try:
        if plan_state_file.exists():
            plan_state_file.unlink()
        # Also clear the active plan reference
        clear_active_plan()
        log_debug(f"Cleared plan state: {plan_state_file.name}")
        return True
    except Exception as e:
        log_debug(f"Error clearing plan state: {e}")
        return False


def task_to_active_form(task: str) -> str:
    """Convert task description to present participle (activeForm) for TodoWrite.

    Examples:
        "Fix authentication bug" -> "Fixing authentication bug"
        "Add new feature" -> "Adding new feature"
        "Running tests" -> "Running tests" (already in -ing form)
    """
    if not task:
        return task

    # Common verbs that need -ing conversion
    verb_mappings = {
        "fix": "Fixing",
        "add": "Adding",
        "create": "Creating",
        "update": "Updating",
        "run": "Running",
        "test": "Testing",
        "deploy": "Deploying",
        "implement": "Implementing",
        "modify": "Modifying",
        "remove": "Removing",
        "delete": "Deleting",
        "refactor": "Refactoring",
        "write": "Writing",
        "read": "Reading",
        "build": "Building",
        "configure": "Configuring",
        "setup": "Setting up",
        "set up": "Setting up",
        "check": "Checking",
        "verify": "Verifying",
        "review": "Reviewing",
        "analyze": "Analyzing",
        "debug": "Debugging",
        "optimize": "Optimizing",
        "install": "Installing",
        "migrate": "Migrating",
        "integrate": "Integrating",
    }

    words = task.split()
    if not words:
        return task

    first_word = words[0].lower()

    # Check if already in -ing form
    if first_word.endswith("ing"):
        return task.capitalize() if task[0].islower() else task

    # Try to convert using mapping
    if first_word in verb_mappings:
        words[0] = verb_mappings[first_word]
        return " ".join(words)

    # Fallback: just capitalize
    return task.capitalize() if task[0].islower() else task


def format_todos_for_claude(items: list) -> str:
    """Format plan items as TodoWrite-ready JSON instructions.

    This generates a JSON array that Claude can use directly with TodoWrite,
    ensuring todos match the plan items exactly for proper sync.
    """
    if not items:
        return ""

    todos = []
    for item in items:
        task = item.get("task", item.get("content", ""))
        status = item.get("status", "pending")

        # Normalize status for TodoWrite
        if status in ["completed", "done"]:
            todo_status = "completed"
        elif status == "in_progress":
            todo_status = "in_progress"
        else:
            todo_status = "pending"

        # Generate activeForm
        active_form = task_to_active_form(task)

        todos.append({
            "content": task,
            "status": todo_status,
            "activeForm": active_form
        })

    msg = "\n\n---\n## 📝 Initialize TodoWrite\n"
    msg += "**IMPORTANT:** Call `TodoWrite` immediately with these exact items to track progress:\n\n"
    msg += "```json\n" + json.dumps(todos, indent=2) + "\n```\n\n"
    msg += "This ensures your todos match the plan items for proper sync tracking.\n"
    msg += "Mark items as `in_progress` when you start working on them."
    return msg


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


def get_available_continuations():
    """Get list of incomplete sessions that can be continued."""
    if not CONTINUATIONS_DIR.exists():
        return []

    continuations = []
    for f in CONTINUATIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            continuations.append({
                "session_id": data.get("session_id"),
                "plan_name": data.get("plan_name", "Unnamed"),
                "progress": f"{data.get('completed_count', 0)}/{data.get('total_count', 0)}",
                "completed_count": data.get("completed_count", 0),
                "total_count": data.get("total_count", 0),
                "saved_at": data.get("saved_at"),
                "accumulated_cost": data.get("accumulated_cost", 0),
                "total_tokens": data.get("total_tokens", 0),
                "file": f
            })
        except Exception:
            continue

    # Sort by saved_at descending (most recent first)
    continuations.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
    return continuations


def format_continuations_message(continuations):
    """Format available continuations for display."""
    if not continuations:
        return "No saved continuations available."

    msg = "## Available Session Continuations\n\n"
    msg += "Previous sessions with incomplete tasks:\n\n"

    for i, c in enumerate(continuations[:5], 1):  # Show max 5
        session_id = c.get("session_id", "unknown")
        session_short = session_id[:8] if session_id else "unknown"
        saved_at = c.get("saved_at", "")[:16] if c.get("saved_at") else "unknown"
        remaining = c.get("total_count", 0) - c.get("completed_count", 0)

        msg += f"**{i}. {c['plan_name']}**\n"
        msg += f"   Progress: {c['progress']} ({remaining} remaining)\n"
        msg += f"   Session: `{session_short}...` | Saved: {saved_at}\n\n"

    msg += "---\n"
    msg += "To continue a session: `@continue {session_id_prefix}`\n"
    msg += "Example: `@continue " + (continuations[0].get("session_id", "abc12345")[:8] if continuations else "abc12345") + "`\n"

    return msg


def load_continuation(session_id_prefix: str):
    """Load a specific continuation by session ID prefix."""
    if not CONTINUATIONS_DIR.exists():
        return None, None

    for f in CONTINUATIONS_DIR.glob("*.json"):
        if f.stem.startswith(session_id_prefix):
            try:
                data = json.loads(f.read_text())
                return data, f
            except Exception:
                continue
    return None, None


def copy_continuation_to_session(continuation: dict, session_id: str, plan_state_file: Path):
    """Copy continuation state to the new session's plan state."""
    try:
        # Create new plan state from continuation
        plan_state = {
            "session_id": session_id,
            "project_name": PROJECT_NAME,
            "plan_source": "continuation",
            "plan_file": continuation.get("plan_file"),
            "name": continuation.get("plan_name", "Continued Plan"),
            "description": f"Continued from session {continuation.get('session_id', 'unknown')[:8]}",
            "items": continuation.get("items", []),
            "verification": {},
            "format": "continuation",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "continued_from": {
                "session_id": continuation.get("session_id"),
                "saved_at": continuation.get("saved_at"),
                "accumulated_cost": continuation.get("accumulated_cost", 0),
                "total_tokens": continuation.get("total_tokens", 0)
            }
        }

        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        plan_state_file.write_text(json.dumps(plan_state, indent=2))

        # Update active plan reference
        save_active_plan(
            session_id=session_id,
            plan_file=plan_state.get("plan_file"),
            name=plan_state.get("name")
        )

        log_debug(f"Copied continuation to session {session_id}")
        return True

    except Exception as e:
        log_debug(f"Error copying continuation: {e}")
        return False


def remove_continuation_file(cont_file: Path):
    """Remove a continuation file after successful continuation."""
    try:
        if cont_file and cont_file.exists():
            cont_file.unlink()
            log_debug(f"Removed continuation file: {cont_file.name}")
    except Exception as e:
        log_debug(f"Error removing continuation file: {e}")


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

        # @plan <name> or @newplan <name>
        plan_match = re.match(r'^@(?:new)?plan\s+(.+)$', prompt, re.IGNORECASE)
        if plan_match:
            plan_name = plan_match.group(1).strip()
            log_debug(f"Session {session_id}: Initializing plan: {plan_name}")

            plan_state = {
                "session_id": session_id,
                "project_name": PROJECT_NAME,
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
                    f"Use `@clearplan` to remove the plan or `@showplan` to see status."
                )
            else:
                output_hook_response(True, message="❌ Failed to initialize plan.")
            sys.exit(0)

        # @clearplan
        if prompt_lower in ["@clearplan", "@clear-plan", "@cleartasks"]:
            log_debug(f"Session {session_id}: Clearing plan")
            if clear_plan_state(plan_state_file):
                output_hook_response(True, message="🗑️ Plan cleared. Stop verification disabled.")
            else:
                output_hook_response(True, message="❌ Failed to clear plan.")
            sys.exit(0)

        # @showplan
        if prompt_lower in ["@showplan", "@show-plan", "@planstatus", "@plan-status"]:
            log_debug(f"Session {session_id}: Showing plan status")
            plan_state = load_plan_state(plan_state_file)
            summary = get_plan_summary(plan_state)
            output_hook_response(True, message=summary)
            sys.exit(0)

        # @continue or @continuations - list or continue from a previous session
        if prompt_lower.startswith("@continue") or prompt_lower == "@continuations":
            parts = prompt.split()

            if len(parts) == 1:
                # Just @continue or @continuations - list available continuations
                log_debug(f"Session {session_id}: Listing available continuations")
                continuations = get_available_continuations()
                msg = format_continuations_message(continuations)
                output_hook_response(True, message=msg)
                sys.exit(0)

            else:
                # @continue {session_id_prefix} - continue from specific session
                session_prefix = parts[1].strip()
                log_debug(f"Session {session_id}: Attempting to continue session {session_prefix}")

                continuation, cont_file = load_continuation(session_prefix)

                if not continuation:
                    output_hook_response(
                        True,
                        message=f"❌ No continuation found for session prefix: `{session_prefix}`\n\n"
                        f"Use `@continue` to see available continuations."
                    )
                    sys.exit(0)

                # Copy continuation to current session
                if copy_continuation_to_session(continuation, session_id, plan_state_file):
                    # Format remaining tasks
                    items = continuation.get("items", [])
                    remaining = [i for i in items if i.get("status") not in ["completed", "done"]]
                    completed_count = continuation.get("completed_count", 0)
                    total_count = continuation.get("total_count", len(items))

                    msg = f"## Continuing: {continuation.get('plan_name', 'Unnamed Plan')}\n\n"
                    msg += f"**Previous progress:** {completed_count}/{total_count} completed\n"
                    msg += f"**From session:** `{continuation.get('session_id', 'unknown')[:8]}...`\n\n"

                    msg += "### Remaining Tasks:\n"
                    for i, item in enumerate(remaining, 1):
                        task = item.get("task", item.get("content", "Unknown task"))
                        status = item.get("status", "pending")
                        icon = "🔄" if status == "in_progress" else "⬜"
                        msg += f"{i}. {icon} {task}\n"

                    msg += "\n---\n"
                    msg += "Plan state loaded. Stop verification is now active.\n"
                    msg += "Complete remaining tasks or use `@clearplan` to start fresh."

                    # Add TodoWrite-ready JSON for immediate initialization
                    todo_msg = format_todos_for_claude(remaining)
                    msg += todo_msg

                    # Remove the continuation file since we're continuing from it
                    remove_continuation_file(cont_file)

                    output_hook_response(True, message=msg)
                else:
                    output_hook_response(
                        True,
                        message=f"❌ Failed to load continuation from session `{session_prefix}`"
                    )

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
