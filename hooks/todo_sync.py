#!/usr/bin/env python3
"""
Todo Sync Hook - Syncs TodoWrite completions to plan_state.json.

Triggers on: PostToolUse with matcher "TodoWrite"
Purpose: Match completed todos to plan items using Claude Haiku 4.5
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.todo_sync_debug.log")


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
            with open(config_file, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_plan_state() -> dict:
    """Load plan state from file."""
    try:
        if PLAN_STATE_FILE.exists():
            with open(PLAN_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return {"items": []}


def save_plan_state(state: dict):
    """Save plan state to file."""
    try:
        HOOKS_DIR.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()

        with open(PLAN_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

        log_debug(f"Saved plan state: {len(state.get('items', []))} items")
        return True
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")
        return False


def match_with_haiku(todo_content: str, plan_items: list) -> int | None:
    """Use Claude Haiku 4.5 via curl to match a todo to a plan item."""

    # Get API key from environment
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log_debug("ANTHROPIC_API_KEY not set, skipping Haiku matching")
        return None

    # Filter to only pending items
    pending_items = [
        (i, item) for i, item in enumerate(plan_items)
        if item.get("status") != "completed"
    ]

    if not pending_items:
        log_debug("No pending plan items to match against")
        return None

    # Build the prompt
    items_text = "\n".join([
        f"{i}: {item.get('task', '')}"
        for i, item in pending_items
    ])

    prompt = f"""Match the completed todo to the most relevant plan item.

Completed Todo: "{todo_content}"

Plan Items (index: task):
{items_text}

Reply with ONLY the index number of the best matching plan item, or "none" if no item matches.
Consider semantic meaning - e.g. "Push files to GitHub" matches "Files uploaded"."""

    # Build request payload
    payload = {
        "model": "claude-haiku-4-5-20250110",
        "max_tokens": 10,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        # Call Anthropic API via curl
        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "https://api.anthropic.com/v1/messages",
                "-H", "Content-Type: application/json",
                "-H", f"x-api-key: {api_key}",
                "-H", "anthropic-version: 2023-06-01",
                "-d", json.dumps(payload)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            log_debug(f"curl failed: {result.stderr}")
            return None

        response = json.loads(result.stdout)

        if "error" in response:
            log_debug(f"API error: {response['error']}")
            return None

        answer = response["content"][0]["text"].strip().lower()
        log_debug(f"Haiku response for '{todo_content[:30]}': {answer}")

        if answer == "none":
            return None

        # Parse the index
        try:
            matched_index = int(answer)
            # Find the original index from pending_items
            for orig_idx, item in pending_items:
                if orig_idx == matched_index:
                    return orig_idx
            # If matched_index is position in pending list, convert to original
            if 0 <= matched_index < len(pending_items):
                return pending_items[matched_index][0]
        except ValueError:
            log_debug(f"Could not parse Haiku response as index: {answer}")
            return None

    except subprocess.TimeoutExpired:
        log_debug("Haiku API call timed out")
        return None
    except Exception as e:
        log_debug(f"Haiku API error: {e}")
        return None

    return None


def main():
    """Main entry point for the hook."""
    try:
        # Check if plan verification is enabled
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            log_debug("Plan verification disabled, skipping todo sync")
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        log_debug(f"Todo sync triggered: {json.dumps(data, indent=2)[:500]}")

        # Extract todos from tool input
        tool_input = data.get("tool_input", {})
        todos = tool_input.get("todos", [])

        if not todos:
            log_debug("No todos in tool input")
            sys.exit(0)

        # Load plan state
        plan_state = load_plan_state()
        plan_items = plan_state.get("items", [])

        if not plan_items:
            log_debug("No plan items to match against")
            sys.exit(0)

        # Track changes
        changes_made = 0

        # Process each completed todo
        for todo in todos:
            if todo.get("status") == "completed":
                content = todo.get("content", "")
                match_index = match_with_haiku(content, plan_items)

                if match_index is not None:
                    if plan_items[match_index].get("status") != "completed":
                        plan_items[match_index]["status"] = "completed"
                        plan_items[match_index]["completed_at"] = datetime.now().isoformat()
                        changes_made += 1
                        log_debug(f"Marked plan item {match_index + 1} as completed: {plan_items[match_index]['task'][:50]}")

        # Save if changes were made
        if changes_made > 0:
            plan_state["items"] = plan_items
            save_plan_state(plan_state)
            log_debug(f"Updated {changes_made} plan items to completed")
        else:
            log_debug("No plan items matched completed todos")

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
    except Exception as e:
        log_debug(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
