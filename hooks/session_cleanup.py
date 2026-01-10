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

# Configuration
HOOKS_DIR = Path(__file__).parent
ARCHIVE_DIR = HOOKS_DIR / "archive"
DEBUG_LOG = HOOKS_DIR.parent / "progress/.session_cleanup_debug.log"
SESSION_HISTORY = HOOKS_DIR.parent / "progress/session_history.json"


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

        # Clean up session files
        cleanup_session_files(plan_state_file, stop_attempts_file, session_id)

        # Generate summary message
        if plan_state and plan_state.get("items"):
            items = plan_state.get("items", [])
            completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
            output_hook_response(
                True,
                f"📦 Session archived: {completed}/{len(items)} items completed\n"
                f"Archive: {Path(archive_path).name if archive_path else 'None'}"
            )
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
