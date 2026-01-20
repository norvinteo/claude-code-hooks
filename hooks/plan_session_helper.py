#!/usr/bin/env python3
"""
Plan Session Helper - Shared utilities for cross-session plan tracking.

This module provides utilities to track the "active plan" across different
Claude sessions. Since session IDs change between conversations, this helps
maintain continuity of plan tracking.

The active_plan.json file stores:
- session_id: The session ID that owns the current active plan
- plan_file: Path to the plan file (for reference)
- name: Plan name (for display)
- updated_at: When this was last updated
"""

import json
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path(__file__).parent
SESSIONS_DIR = HOOKS_DIR / "sessions"
ACTIVE_PLAN_FILE = SESSIONS_DIR / "active_plan.json"


def get_session_files(session_id: str) -> tuple:
    """Get session-scoped file paths."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    plan_state_file = SESSIONS_DIR / f"{session_id}_plan_state.json"
    stop_attempts_file = SESSIONS_DIR / f"{session_id}_stop_attempts.json"
    return plan_state_file, stop_attempts_file


def load_active_plan() -> dict:
    """Load the active plan reference."""
    try:
        if ACTIVE_PLAN_FILE.exists():
            return json.loads(ACTIVE_PLAN_FILE.read_text())
    except Exception:
        pass
    return None


def save_active_plan(session_id: str, plan_file: str = None, name: str = None):
    """Save the active plan reference."""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": session_id,
            "plan_file": plan_file,
            "name": name,
            "updated_at": datetime.now().isoformat()
        }
        ACTIVE_PLAN_FILE.write_text(json.dumps(data, indent=2))
        return True
    except Exception:
        return False


def clear_active_plan():
    """Clear the active plan reference."""
    try:
        if ACTIVE_PLAN_FILE.exists():
            ACTIVE_PLAN_FILE.unlink()
        return True
    except Exception:
        return False


def get_plan_state_file(session_id: str) -> Path:
    """
    Get the plan state file for a session, with fallback to active plan.

    Priority:
    1. Current session's plan state file (if it exists and has items)
    2. Active plan's session file (if set)
    3. None
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # First check current session
    current_file = SESSIONS_DIR / f"{session_id}_plan_state.json"
    if current_file.exists():
        try:
            data = json.loads(current_file.read_text())
            # Only use if it has a name (indicates it's a real plan)
            if data.get("name") or data.get("items"):
                return current_file
        except Exception:
            pass

    # Fallback to active plan
    active = load_active_plan()
    if active and active.get("session_id"):
        active_file = SESSIONS_DIR / f"{active['session_id']}_plan_state.json"
        if active_file.exists():
            return active_file

    return None


def load_plan_state_with_fallback(session_id: str) -> tuple:
    """
    Load plan state with fallback to active plan.

    Returns:
        tuple: (plan_state dict, plan_state_file Path, is_fallback bool)
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # First check current session
    current_file = SESSIONS_DIR / f"{session_id}_plan_state.json"
    if current_file.exists():
        try:
            data = json.loads(current_file.read_text())
            if data.get("name") or data.get("session_id"):
                return data, current_file, False
        except Exception:
            pass

    # Fallback to active plan
    active = load_active_plan()
    if active and active.get("session_id"):
        active_file = SESSIONS_DIR / f"{active['session_id']}_plan_state.json"
        if active_file.exists():
            try:
                data = json.loads(active_file.read_text())
                return data, active_file, True
            except Exception:
                pass

    return None, current_file, False


def find_most_recent_plan() -> tuple:
    """
    Find the most recently updated plan state file.

    Returns:
        tuple: (plan_state dict, plan_state_file Path) or (None, None)
    """
    if not SESSIONS_DIR.exists():
        return None, None

    most_recent = None
    most_recent_file = None
    most_recent_time = None

    for f in SESSIONS_DIR.glob("*_plan_state.json"):
        try:
            data = json.loads(f.read_text())
            # Only consider files with actual plan data
            if not (data.get("name") or data.get("items")):
                continue

            updated = data.get("updated_at") or data.get("created_at")
            if updated:
                updated_time = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if most_recent_time is None or updated_time > most_recent_time:
                    most_recent_time = updated_time
                    most_recent = data
                    most_recent_file = f
        except Exception:
            continue

    return most_recent, most_recent_file


def link_cost_session_to_plan(cost_session_id: str) -> bool:
    """
    Link a cost tracking session to the active plan.

    This associates the Claude conversation session ID (used for cost tracking)
    with the active plan session, allowing costs to be displayed with the plan.

    Args:
        cost_session_id: The session ID from cost tracking (Claude conversation ID)

    Returns:
        bool: True if successfully linked, False otherwise
    """
    try:
        active = load_active_plan()
        if not active:
            return False

        plan_session_id = active.get("session_id")
        if not plan_session_id:
            return False

        # Update active_plan.json with the cost session ID
        active["cost_session_id"] = cost_session_id
        active["updated_at"] = datetime.now().isoformat()
        ACTIVE_PLAN_FILE.write_text(json.dumps(active, indent=2))

        # Also update the plan state file with the cost session ID
        plan_state_file = SESSIONS_DIR / f"{plan_session_id}_plan_state.json"
        if plan_state_file.exists():
            plan_state = json.loads(plan_state_file.read_text())
            plan_state["cost_session_id"] = cost_session_id
            plan_state["updated_at"] = datetime.now().isoformat()
            plan_state_file.write_text(json.dumps(plan_state, indent=2))

        return True
    except Exception:
        return False


def update_plan_accumulated_cost(cost: float, input_tokens: int, output_tokens: int) -> bool:
    """
    Update the accumulated cost in the active plan's state file.

    Args:
        cost: Cost to add
        input_tokens: Input tokens to add
        output_tokens: Output tokens to add

    Returns:
        bool: True if successfully updated, False otherwise
    """
    try:
        active = load_active_plan()
        if not active:
            return False

        plan_session_id = active.get("session_id")
        if not plan_session_id:
            return False

        plan_state_file = SESSIONS_DIR / f"{plan_session_id}_plan_state.json"
        if not plan_state_file.exists():
            return False

        plan_state = json.loads(plan_state_file.read_text())

        # Initialize cost tracking fields if not present
        if "accumulated_cost" not in plan_state:
            plan_state["accumulated_cost"] = 0.0
            plan_state["total_input_tokens"] = 0
            plan_state["total_output_tokens"] = 0
            plan_state["tool_calls"] = 0

        # Update cost data
        plan_state["accumulated_cost"] += cost
        plan_state["total_input_tokens"] += input_tokens
        plan_state["total_output_tokens"] += output_tokens
        plan_state["tool_calls"] = plan_state.get("tool_calls", 0) + 1
        plan_state["updated_at"] = datetime.now().isoformat()

        plan_state_file.write_text(json.dumps(plan_state, indent=2))
        return True
    except Exception:
        return False


def get_active_plan_session_id() -> str:
    """
    Get the plan session ID from the active plan.

    Returns:
        str: The plan session ID, or None if no active plan
    """
    active = load_active_plan()
    if active:
        return active.get("session_id")
    return None
