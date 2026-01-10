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

        # Check if there's an active plan
        has_active_plan = plan_state.get("name") or plan_state.get("session_id")

        if not has_active_plan:
            log_debug("No active plan, skipping todo sync")
            sys.exit(0)

        # Track changes
        changes_made = 0

        # If plan has no items yet, add todos as plan items
        if not plan_items:
            log_debug("Plan has no items, adding todos as plan items")
            for i, todo in enumerate(todos):
                content = todo.get("content", "")
                status = todo.get("status", "pending")
                plan_items.append({
                    "id": i + 1,
                    "task": content,
                    "status": "completed" if status == "completed" else "pending",
                    "added_at": datetime.now().isoformat()
                })
                if status == "completed":
                    plan_items[-1]["completed_at"] = datetime.now().isoformat()
                changes_made += 1
                log_debug(f"Added plan item: {content[:50]}")
        else:
            # Sync todos with existing plan items
            existing_tasks = {item.get("task", "").lower(): i for i, item in enumerate(plan_items)}

            for todo in todos:
                content = todo.get("content", "")
                status = todo.get("status", "pending")

                # Check if this todo already exists in plan (exact match)
                exact_match_idx = existing_tasks.get(content.lower())

                if exact_match_idx is not None:
                    # Exact match found - update status if completed
                    if status == "completed" and plan_items[exact_match_idx].get("status") != "completed":
                        plan_items[exact_match_idx]["status"] = "completed"
                        plan_items[exact_match_idx]["completed_at"] = datetime.now().isoformat()
                        changes_made += 1
                        log_debug(f"Exact match - marked complete: {content[:50]}")
                else:
                    # No exact match - try Haiku for semantic match on completed todos
                    if status == "completed":
                        match_index = match_with_haiku(content, plan_items)
                        if match_index is not None:
                            if plan_items[match_index].get("status") != "completed":
                                plan_items[match_index]["status"] = "completed"
                                plan_items[match_index]["completed_at"] = datetime.now().isoformat()
                                changes_made += 1
                                log_debug(f"Haiku match - marked complete: {plan_items[match_index]['task'][:50]}")
                        else:
                            # No match found - add as new completed item
                            new_id = max((item.get("id", 0) for item in plan_items), default=0) + 1
                            plan_items.append({
                                "id": new_id,
                                "task": content,
                                "status": "completed",
                                "added_at": datetime.now().isoformat(),
                                "completed_at": datetime.now().isoformat()
                            })
                            existing_tasks[content.lower()] = len(plan_items) - 1
                            changes_made += 1
                            log_debug(f"Added new completed item: {content[:50]}")
                    else:
                        # Add new pending todo as plan item
                        new_id = max((item.get("id", 0) for item in plan_items), default=0) + 1
                        plan_items.append({
                            "id": new_id,
                            "task": content,
                            "status": "pending",
                            "added_at": datetime.now().isoformat()
                        })
                        existing_tasks[content.lower()] = len(plan_items) - 1
                        changes_made += 1
                        log_debug(f"Added new pending item: {content[:50]}")

        # Save if changes were made
        if changes_made > 0:
            plan_state["items"] = plan_items
            save_plan_state(plan_state)
            log_debug(f"Updated plan: {changes_made} changes made")
        else:
            log_debug("No changes to plan")

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
    except Exception as e:
        log_debug(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
