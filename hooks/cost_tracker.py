#!/usr/bin/env python3
"""
Cost Tracker Hook - Tracks API usage and enforces cost limits.

Triggers on: PostToolUse (all tools)
Purpose: Track token usage per session and warn/block when limits exceeded.

Environment Variables:
- CLAUDE_MAX_SESSION_COST: Maximum cost per session in USD (default: 10.00)
- CLAUDE_COST_WARNING_THRESHOLD: Percentage to warn at (default: 0.8 = 80%)
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path(__file__).parent
COST_LOG = HOOKS_DIR.parent / "progress/api_costs.json"
DEBUG_LOG = HOOKS_DIR.parent / "progress/.cost_tracker_debug.log"
CONFIG_FILE = HOOKS_DIR / "config.json"

# Import plan session helper for linking costs to plans
try:
    from plan_session_helper import (
        link_cost_session_to_plan,
        update_plan_accumulated_cost,
        load_active_plan
    )
    PLAN_HELPER_AVAILABLE = True
except ImportError:
    PLAN_HELPER_AVAILABLE = False


def load_config() -> dict:
    """Load config from file."""
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    return {}


def get_cost_limits() -> tuple:
    """Get cost limits from config, env vars, or defaults."""
    config = load_config()

    # Priority: env vars > config.json > defaults
    max_cost = float(os.environ.get(
        "CLAUDE_MAX_SESSION_COST",
        config.get("max_session_cost", 10.00)
    ))
    warning_threshold = float(os.environ.get(
        "CLAUDE_COST_WARNING_THRESHOLD",
        config.get("cost_warning_threshold", 0.8)
    ))

    return max_cost, warning_threshold

# Pricing per 1M tokens (as of Jan 2026)
PRICING = {
    "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    # Default fallback (Opus pricing)
    "default": {"input": 15.00, "output": 75.00}
}


def log_debug(message: str):
    """Log debug message to file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_cost_log() -> dict:
    """Load cost log from file."""
    try:
        if COST_LOG.exists():
            return json.loads(COST_LOG.read_text())
    except Exception as e:
        log_debug(f"Error loading cost log: {e}")
    return {"sessions": {}, "total_cost": 0.0}


def save_cost_log(data: dict):
    """Save cost log to file."""
    try:
        COST_LOG.parent.mkdir(parents=True, exist_ok=True)
        data["_last_updated"] = datetime.now().isoformat()
        COST_LOG.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log_debug(f"Error saving cost log: {e}")


def calculate_cost(input_tokens: int, output_tokens: int, model: str = "default") -> float:
    """Calculate cost based on token usage and model."""
    pricing = PRICING.get(model, PRICING["default"])

    # Cost per token (pricing is per 1M tokens)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return input_cost + output_cost


def get_session_cost(session_id: str) -> dict:
    """Get cost data for a session."""
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
    """Update session cost and return new totals."""
    cost_log = load_cost_log()
    sessions = cost_log.get("sessions", {})

    is_new_session = session_id not in sessions
    if is_new_session:
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

    # Update global total
    cost_log["total_cost"] = sum(s.get("total_cost", 0) for s in sessions.values())
    cost_log["sessions"] = sessions

    save_cost_log(cost_log)

    # Link cost session to active plan and update accumulated cost
    if PLAN_HELPER_AVAILABLE:
        try:
            # Link this cost session to the active plan (if exists)
            if is_new_session:
                link_cost_session_to_plan(session_id)
                log_debug(f"Linked cost session {session_id} to active plan")

            # Update the active plan's accumulated cost
            update_plan_accumulated_cost(cost, input_tokens, output_tokens)
        except Exception as e:
            log_debug(f"Error updating plan cost: {e}")

    return session


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def get_usage_from_transcript(transcript_path: str) -> dict:
    """Read the most recent usage data from the transcript file."""
    try:
        if not transcript_path or not Path(transcript_path).exists():
            return {}

        # Read the last few lines to find the most recent assistant message with usage
        with open(transcript_path, 'r') as f:
            lines = f.readlines()

        # Search from the end for an assistant message with usage
        for line in reversed(lines[-50:]):  # Check last 50 entries
            try:
                entry = json.loads(line.strip())
                if entry.get('type') == 'assistant':
                    message = entry.get('message', {})
                    if isinstance(message, dict) and 'usage' in message:
                        usage = message['usage']
                        model = message.get('model', 'default')
                        return {
                            'usage': usage,
                            'model': model,
                            'input_tokens': usage.get('input_tokens', 0),
                            'output_tokens': usage.get('output_tokens', 0),
                            'cache_read': usage.get('cache_read_input_tokens', 0),
                            'cache_creation': usage.get('cache_creation_input_tokens', 0),
                        }
            except json.JSONDecodeError:
                continue

        return {}
    except Exception as e:
        log_debug(f"Error reading transcript: {e}")
        return {}


def main():
    """Main entry point for the hook."""
    try:
        # Get cost limits from config
        max_session_cost, warning_threshold = get_cost_limits()

        # Check if cost tracking is enabled
        config = load_config()
        if not config.get("cost_tracking", True):
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        session_id = data.get("session_id", "unknown")
        transcript_path = data.get("transcript_path", "")

        # Try to get usage from transcript file (most reliable source)
        transcript_usage = get_usage_from_transcript(transcript_path)

        if transcript_usage:
            usage = transcript_usage.get('usage', {})
            model = transcript_usage.get('model', 'default')
            input_tokens = transcript_usage.get('input_tokens', 0)
            output_tokens = transcript_usage.get('output_tokens', 0)

            log_debug(f"Session {session_id}: From transcript - model={model}, in={input_tokens}, out={output_tokens}")

            if input_tokens > 0 or output_tokens > 0:
                # Calculate cost for this call
                call_cost = calculate_cost(input_tokens, output_tokens, model)

                # Update session totals
                session = update_session_cost(session_id, call_cost, input_tokens, output_tokens)
                total_cost = session["total_cost"]

                log_debug(f"Session {session_id}: +${call_cost:.4f} = ${total_cost:.4f} total")

                # Check limits and respond
                if total_cost >= max_session_cost:
                    output_hook_response(
                        False,
                        f"⚠️ Session cost limit (${max_session_cost:.2f}) exceeded!\n"
                        f"Current session: ${total_cost:.2f}"
                    )
                    sys.exit(0)

                warning_level = max_session_cost * warning_threshold
                if total_cost >= warning_level:
                    remaining = max_session_cost - total_cost
                    output_hook_response(
                        True,
                        f"💰 Cost: ${total_cost:.2f} / ${max_session_cost:.2f} ({(total_cost/max_session_cost)*100:.0f}%)"
                    )
                    sys.exit(0)

        # Normal case - continue
        output_hook_response(True)

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True)


if __name__ == "__main__":
    main()
