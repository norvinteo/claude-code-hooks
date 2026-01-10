#!/usr/bin/env python3
"""
Session Cleanup Hook - Archives plan state and cleans up session data.

Triggers on: Stop (when allowed)
Purpose: Archive completed plans and clean up temporary session data.
"""

import json
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
STOP_ATTEMPTS_FILE = HOOKS_DIR / "stop_attempts.json"
ARCHIVE_DIR = HOOKS_DIR / "archive"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.session_cleanup_debug.log")
SESSION_HISTORY = Path("{{PROJECT_DIR}}/progress/session_history.json")


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            return json.loads(PLAN_STATE_FILE.read_text())
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def archive_plan_state(plan_state: dict, session_id: str) -> str:
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_name = plan_state.get("name", "unnamed")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in plan_name)[:30]
        archive_file = ARCHIVE_DIR / f"plan_{timestamp}_{safe_name}.json"

        plan_state["archived_at"] = datetime.now().isoformat()
        plan_state["final_session_id"] = session_id

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
    try:
        history = {"sessions": []}
        if SESSION_HISTORY.exists():
            try:
                history = json.loads(SESSION_HISTORY.read_text())
            except Exception:
                history = {"sessions": []}

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

        if len(history["sessions"]) > 100:
            history["sessions"] = history["sessions"][-100:]

        SESSION_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        SESSION_HISTORY.write_text(json.dumps(history, indent=2))
        log_debug(f"Updated session history")

    except Exception as e:
        log_debug(f"Error updating session history: {e}")


def cleanup_temp_files(session_id: str):
    try:
        if STOP_ATTEMPTS_FILE.exists():
            try:
                data = json.loads(STOP_ATTEMPTS_FILE.read_text())
                if session_id in data:
                    del data[session_id]
                    STOP_ATTEMPTS_FILE.write_text(json.dumps(data, indent=2))
                    log_debug(f"Cleared stop attempts for session {session_id}")
            except Exception:
                pass

        if ARCHIVE_DIR.exists():
            archives = sorted(ARCHIVE_DIR.glob("plan_*.json"))
            if len(archives) > 50:
                for old_archive in archives[:-50]:
                    try:
                        old_archive.unlink()
                        log_debug(f"Removed old archive: {old_archive.name}")
                    except Exception:
                        pass

    except Exception as e:
        log_debug(f"Error cleaning up temp files: {e}")


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def load_config() -> dict:
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            return json.loads(config_file.read_text())
    except Exception:
        pass
    return {}


def has_incomplete_items(plan_state: dict) -> bool:
    if not plan_state or not plan_state.get("items"):
        return False
    for item in plan_state.get("items", []):
        if item.get("status") not in ["completed", "done"]:
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "unknown")
        log_debug(f"Session cleanup for: {session_id}")

        config = load_config()
        plan_state_check = load_plan_state()

        if config.get("plan_verification", False) and has_incomplete_items(plan_state_check):
            stop_attempts_data = {}
            if STOP_ATTEMPTS_FILE.exists():
                try:
                    stop_attempts_data = json.loads(STOP_ATTEMPTS_FILE.read_text())
                except Exception:
                    pass

            max_attempts = config.get("max_stop_attempts", 5)
            current_attempts = stop_attempts_data.get(session_id, 0)

            if current_attempts > 0 and current_attempts < max_attempts:
                log_debug(f"Stop likely blocked (attempts: {current_attempts}/{max_attempts}), skipping cleanup")
                output_hook_response(True)
                sys.exit(0)

        plan_state = load_plan_state()

        archive_path = None

        if plan_state and plan_state.get("items"):
            archive_path = archive_plan_state(plan_state, session_id)

            if archive_path:
                try:
                    PLAN_STATE_FILE.unlink()
                    log_debug("Cleared active plan state after archiving")
                except Exception:
                    pass

        update_session_history(session_id, plan_state, archive_path)
        cleanup_temp_files(session_id)

        if plan_state and plan_state.get("items"):
            items = plan_state.get("items", [])
            completed = sum(1 for i in items if i.get("status") in ["completed", "done"])
            output_hook_response(
                True,
                f"Session archived: {completed}/{len(items)} items completed\n"
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
