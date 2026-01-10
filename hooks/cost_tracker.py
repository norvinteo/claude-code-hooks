#!/usr/bin/env python3
"""
Cost Tracker Hook - Tracks API usage and enforces cost limits.

Triggers on: PostToolUse (all tools)
Purpose: Track token usage per session and warn/block when limits exceeded.
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
COST_LOG = Path("{{PROJECT_DIR}}/progress/api_costs.json")
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.cost_tracker_debug.log")
CONFIG_FILE = HOOKS_DIR / "config.json"


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    return {}


def get_cost_limits() -> tuple:
    config = load_config()
    max_cost = float(os.environ.get(
        "CLAUDE_MAX_SESSION_COST",
        config.get("max_session_cost", 10.00)
    ))
    warning_threshold = float(os.environ.get(
        "CLAUDE_COST_WARNING_THRESHOLD",
        config.get("cost_warning_threshold", 0.8)
    ))
    return max_cost, warning_threshold


PRICING = {
    "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    "default": {"input": 15.00, "output": 75.00}
}


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_cost_log() -> dict:
    try:
        if COST_LOG.exists():
            return json.loads(COST_LOG.read_text())
    except Exception as e:
        log_debug(f"Error loading cost log: {e}")
    return {"sessions": {}, "total_cost": 0.0}


def save_cost_log(data: dict):
    try:
        COST_LOG.parent.mkdir(parents=True, exist_ok=True)
        data["_last_updated"] = datetime.now().isoformat()
        COST_LOG.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log_debug(f"Error saving cost log: {e}")


def calculate_cost(input_tokens: int, output_tokens: int, model: str = "default") -> float:
    pricing = PRICING.get(model, PRICING["default"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def get_session_cost(session_id: str) -> dict:
    cost_log = load_cost_log()
    sessions = cost_log.get("sessions", {})

    if session_id not in sessions:
        sessions[session_id] = {
            "total_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": 0,
            "started_at": datetime.now().isoformat()
        }
        cost_log["sessions"] = sessions
        save_cost_log(cost_log)

    return sessions[session_id]


def update_session_cost(session_id: str, cost: float, input_tokens: int, output_tokens: int) -> dict:
    cost_log = load_cost_log()
    sessions = cost_log.get("sessions", {})

    if session_id not in sessions:
        sessions[session_id] = {
            "total_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": 0,
            "started_at": datetime.now().isoformat()
        }

    session = sessions[session_id]
    session["total_cost"] += cost
    session["input_tokens"] += input_tokens
    session["output_tokens"] += output_tokens
    session["tool_calls"] += 1
    session["last_updated"] = datetime.now().isoformat()

    cost_log["total_cost"] = sum(s.get("total_cost", 0) for s in sessions.values())
    cost_log["sessions"] = sessions

    save_cost_log(cost_log)
    return session


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    try:
        max_session_cost, warning_threshold = get_cost_limits()

        config = load_config()
        if not config.get("cost_tracking", True):
            output_hook_response(True)
            sys.exit(0)

        data = json.load(sys.stdin)
        session_id = data.get("session_id", "unknown")

        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        if input_tokens == 0 and output_tokens == 0:
            output_hook_response(True)
            sys.exit(0)

        model = data.get("model", "default")
        call_cost = calculate_cost(input_tokens, output_tokens, model)
        session = update_session_cost(session_id, call_cost, input_tokens, output_tokens)
        total_cost = session["total_cost"]

        log_debug(f"Session {session_id}: +${call_cost:.4f} = ${total_cost:.4f} total")

        if total_cost >= max_session_cost:
            log_debug(f"Session {session_id}: Cost limit exceeded! ${total_cost:.2f} >= ${max_session_cost:.2f}")
            output_hook_response(
                False,
                f"Session cost limit (${max_session_cost:.2f}) exceeded!\n"
                f"Current session: ${total_cost:.2f}\n"
                f"Tokens used: {session['input_tokens']:,} in / {session['output_tokens']:,} out\n"
                f"Use 'force stop' or start a new session to continue."
            )
            sys.exit(0)

        warning_level = max_session_cost * warning_threshold
        if total_cost >= warning_level:
            remaining = max_session_cost - total_cost
            output_hook_response(
                True,
                f"Cost warning: ${total_cost:.2f} / ${max_session_cost:.2f} ({(total_cost/max_session_cost)*100:.0f}%)\n"
                f"${remaining:.2f} remaining before limit."
            )
            sys.exit(0)

        output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
