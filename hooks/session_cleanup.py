#!/usr/bin/env python3
"""
Session Cleanup Hook - Archives plan state and cleans up session data.

Triggers on: Stop (when allowed)
Purpose: Archive completed plans and clean up temporary session data.

This hook runs AFTER stop_verifier allows the stop, so it only runs
when the session is actually ending (all items complete, force stop, or no plan).
"""

import json
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path

# Configuration - paths relative to this script
HOOKS_DIR = Path(__file__).parent
ARCHIVE_DIR = HOOKS_DIR / "archive"
CONTINUATIONS_DIR = HOOKS_DIR.parent / "continuations"
DEBUG_LOG = HOOKS_DIR.parent.parent / "progress" / ".session_cleanup_debug.log"
SESSION_HISTORY = HOOKS_DIR.parent.parent / "progress" / "session_history.json"
DAILY_PROGRESS_DIR = HOOKS_DIR.parent.parent / "progress" / "daily"


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


def archive_plan_state(plan_state: dict, session_id: str) -> str:
    """Archive the plan state and return archive path."""
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        # Generate archive filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_name = plan_state.get("name", "unnamed")
        # Sanitize plan name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in plan_name)[:30]
        archive_file = ARCHIVE_DIR / f"plan_{timestamp}_{safe_name}.json"

        # Add archive metadata
        plan_state["archived_at"] = datetime.now().isoformat()
        plan_state["final_session_id"] = session_id

        # Calculate final stats
        items = plan_state.get("items", [])
        completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
        plan_state["final_stats"] = {
            "total_items": len(items),
            "completed_items": completed,
            "completion_rate": (completed / len(items) * 100) if items else 0
        }

        archive_file.write_text(json.dumps(plan_state, indent=2))
        log_debug(f"Archived plan to: {archive_file}")

        return str(archive_file)

    except Exception as e:
        log_debug(f"Error archiving plan: {e}")
        return None


def update_session_history(session_id: str, plan_state: dict, archive_path: str):
    """Update session history with this session's summary."""
    try:
        history = {"sessions": []}
        if SESSION_HISTORY.exists():
            try:
                history = json.loads(SESSION_HISTORY.read_text())
            except Exception:
                history = {"sessions": []}

        # Create session entry
        items = plan_state.get("items", []) if plan_state else []
        completed = sum(1 for i in items if i.get("status") in ["completed", "done"])

        session_entry = {
            "session_id": session_id,
            "ended_at": datetime.now().isoformat(),
            "plan_name": plan_state.get("name") if plan_state else None,
            "items_total": len(items),
            "items_completed": completed,
            "archive_path": archive_path,
            "started_at": plan_state.get("created_at") if plan_state else None
        }

        history["sessions"].append(session_entry)
        history["_last_updated"] = datetime.now().isoformat()

        # Keep only last 100 sessions
        if len(history["sessions"]) > 100:
            history["sessions"] = history["sessions"][-100:]

        SESSION_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        SESSION_HISTORY.write_text(json.dumps(history, indent=2))
        log_debug(f"Updated session history")

    except Exception as e:
        log_debug(f"Error updating session history: {e}")


def log_to_daily_progress(plan_state: dict, session_id: str):
    """Log completed session to daily progress file."""
    try:
        if not plan_state:
            log_debug("No plan state to log to daily progress")
            return

        items = plan_state.get("items", [])
        if not items:
            log_debug("No items to log to daily progress")
            return

        # Only log if there are completed items
        completed_items = [i for i in items if i.get("status") in ["completed", "done"]]
        if not completed_items:
            log_debug("No completed items to log")
            return

        # Get plan metadata
        plan_name = plan_state.get("name", "Unnamed Session")
        cost = plan_state.get("accumulated_cost", 0)
        input_tokens = plan_state.get("total_input_tokens", 0)
        output_tokens = plan_state.get("total_output_tokens", 0)
        tool_calls = plan_state.get("tool_calls", 0)
        created_at = plan_state.get("created_at", "")

        # Create daily progress file path
        today = datetime.now().strftime("%Y-%m-%d")
        DAILY_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        daily_file = DAILY_PROGRESS_DIR / f"{today}.md"

        # Build the log entry
        entry_lines = []
        entry_lines.append(f"\n---\n")
        entry_lines.append(f"## {plan_name}\n")
        entry_lines.append(f"*Session: `{session_id[:8]}...` | Logged: {datetime.now().strftime('%H:%M:%S')}*\n")

        # Add cost info if available
        if cost > 0 or tool_calls > 0:
            entry_lines.append(f"\n**Stats:** ${cost:.2f} cost | {input_tokens + output_tokens:,} tokens | {tool_calls} tool calls\n")

        # Add completed items
        entry_lines.append(f"\n### Completed ({len(completed_items)}/{len(items)})\n")
        for item in completed_items:
            task = item.get("task", item.get("content", "Unknown task"))
            entry_lines.append(f"- [x] {task}\n")

        # Add pending items if any
        pending_items = [i for i in items if i.get("status") not in ["completed", "done"]]
        if pending_items:
            entry_lines.append(f"\n### Pending ({len(pending_items)})\n")
            for item in pending_items:
                task = item.get("task", item.get("content", "Unknown task"))
                status = item.get("status", "pending")
                icon = "[>]" if status == "in_progress" else "[ ]"
                entry_lines.append(f"- {icon} {task}\n")

        # Write to daily file
        if daily_file.exists():
            # Append to existing file
            with open(daily_file, "a") as f:
                f.writelines(entry_lines)
        else:
            # Create new file with header
            header = f"# Progress Log - {today}\n\n"
            with open(daily_file, "w") as f:
                f.write(header)
                f.writelines(entry_lines)

        log_debug(f"Logged session to daily progress: {daily_file}")

    except Exception as e:
        log_debug(f"Error logging to daily progress: {e}")


def cleanup_session_files(plan_state_file: Path, stop_attempts_file: Path, session_id: str):
    """Clean up session-specific files after archiving."""
    try:
        # Clear the session's plan state file
        if plan_state_file.exists():
            try:
                plan_state_file.unlink()
                log_debug(f"Cleared plan state for session {session_id}")
            except Exception:
                pass

        # Clear stop attempts for this session
        if stop_attempts_file.exists():
            try:
                stop_attempts_file.unlink()
                log_debug(f"Cleared stop attempts for session {session_id}")
            except Exception:
                pass

        # Clean up old archives (keep last 50)
        if ARCHIVE_DIR.exists():
            archives = sorted(ARCHIVE_DIR.glob("plan_*.json"))
            if len(archives) > 50:
                for old_archive in archives[:-50]:
                    try:
                        old_archive.unlink()
                        log_debug(f"Removed old archive: {old_archive.name}")
                    except Exception:
                        pass

        # Clean up stale session files (older than 7 days)
        sessions_dir = HOOKS_DIR / "sessions"
        if sessions_dir.exists():
            import time
            cutoff = time.time() - (7 * 24 * 60 * 60)  # 7 days ago
            for session_file in sessions_dir.glob("*_*.json"):
                try:
                    if session_file.stat().st_mtime < cutoff:
                        session_file.unlink()
                        log_debug(f"Removed stale session file: {session_file.name}")
                except Exception:
                    pass

    except Exception as e:
        log_debug(f"Error cleaning up session files: {e}")


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def load_config() -> dict:
    """Load config from file."""
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            return json.loads(config_file.read_text())
    except Exception:
        pass
    return {}


def has_incomplete_items(plan_state: dict) -> bool:
    """Check if plan has incomplete items."""
    if not plan_state or not plan_state.get("items"):
        return False
    for item in plan_state.get("items", []):
        if item.get("status") not in ["completed", "done"]:
            return True
    return False


def save_continuation_state(plan_state: dict, session_id: str):
    """Save session state for potential continuation by other sessions."""
    if not plan_state or not plan_state.get("items"):
        log_debug("No plan state to save for continuation")
        return

    items = plan_state.get("items", [])
    incomplete = [i for i in items if i.get("status") not in ["completed", "done"]]

    CONTINUATIONS_DIR.mkdir(parents=True, exist_ok=True)
    continuation_file = CONTINUATIONS_DIR / f"{session_id}.json"

    if not incomplete:
        # Plan complete - remove continuation file if exists
        if continuation_file.exists():
            try:
                continuation_file.unlink()
                log_debug(f"Removed continuation file (plan complete): {session_id}")
            except Exception:
                pass
        return

    continuation = {
        "session_id": session_id,
        "plan_name": plan_state.get("name", "Unnamed Plan"),
        "items": items,
        "completed_count": len(items) - len(incomplete),
        "total_count": len(items),
        "saved_at": datetime.now().isoformat(),
        "accumulated_cost": plan_state.get("accumulated_cost", 0),
        "total_tokens": (plan_state.get("total_input_tokens", 0) +
                        plan_state.get("total_output_tokens", 0)),
        "created_at": plan_state.get("created_at"),
        "plan_file": plan_state.get("plan_file")
    }

    try:
        continuation_file.write_text(json.dumps(continuation, indent=2))
        log_debug(f"Saved continuation state: {session_id} ({len(incomplete)} incomplete items)")
    except Exception as e:
        log_debug(f"Error saving continuation state: {e}")


def cleanup_old_continuations():
    """Remove continuation files older than 7 days."""
    if not CONTINUATIONS_DIR.exists():
        return

    import time
    cutoff = time.time() - (7 * 24 * 60 * 60)  # 7 days ago
    removed_count = 0

    for f in CONTINUATIONS_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed_count += 1
                log_debug(f"Removed old continuation: {f.name}")
        except Exception:
            pass

    if removed_count > 0:
        log_debug(f"Cleaned up {removed_count} old continuation files")


def main():
    """Main entry point for the hook."""
    try:
        # Read JSON input from stdin
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "default")
        log_debug(f"Session cleanup for: {session_id}")

        # Get session-scoped file paths
        plan_state_file, stop_attempts_file = get_session_files(session_id)

        # Safety check: if plan verification is enabled and items are incomplete,
        # stop_verifier should have blocked. Only proceed if actually stopping.
        config = load_config()
        plan_state_check = load_plan_state(plan_state_file)

        if config.get("plan_verification", False) and has_incomplete_items(plan_state_check):
            # Check if there's a marker that stop was allowed (force stop or loop prevention)
            stop_attempts_data = {}
            if stop_attempts_file.exists():
                try:
                    stop_attempts_data = json.loads(stop_attempts_file.read_text())
                except Exception:
                    pass

            # If stop attempts exist but haven't hit max, stop_verifier likely blocked
            # In this case, we shouldn't clean up yet
            max_attempts = config.get("max_stop_attempts", 5)
            current_attempts = stop_attempts_data.get("attempts", 0)

            if current_attempts > 0 and current_attempts < max_attempts:
                log_debug(f"Stop likely blocked (attempts: {current_attempts}/{max_attempts}), skipping cleanup")
                output_hook_response(True)
                sys.exit(0)

        # Load plan state
        plan_state = load_plan_state(plan_state_file)

        # Save continuation state for incomplete plans (before archiving)
        if plan_state and plan_state.get("items"):
            save_continuation_state(plan_state, session_id)

        archive_path = None

        # Archive if there's a plan
        if plan_state and plan_state.get("items"):
            archive_path = archive_plan_state(plan_state, session_id)

            # Clear the active plan state after archiving
            if archive_path:
                try:
                    plan_state_file.unlink()
                    log_debug("Cleared active plan state after archiving")
                except Exception:
                    pass

        # Update session history
        update_session_history(session_id, plan_state, archive_path)

        # Log to daily progress file
        log_to_daily_progress(plan_state, session_id)

        # Clean up session files
        cleanup_session_files(plan_state_file, stop_attempts_file, session_id)

        # Clean up old continuation files (older than 7 days)
        cleanup_old_continuations()

        # Generate summary message
        if plan_state and plan_state.get("items"):
            items = plan_state.get("items", [])
            completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
            incomplete = len(items) - completed

            msg = f"Session archived: {completed}/{len(items)} items completed\n"
            msg += f"Archive: {Path(archive_path).name if archive_path else 'None'}"

            if incomplete > 0:
                msg += f"\n\nContinuation saved with {incomplete} pending tasks."
                msg += f"\nNew sessions can continue with: `@continue {session_id[:8]}`"

            output_hook_response(True, msg)
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
