#!/usr/bin/env python3
"""
Todo Sync Hook - Syncs TodoWrite completions to plan_state.json.

Triggers on: PostToolUse with matcher "TodoWrite"
Purpose: Match completed todos to plan items and update their status
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.todo_sync_debug.log")


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_config() -> dict:
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            with open(PLAN_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return {"items": []}


def save_plan_state(state: dict):
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


def normalize_text(text: str) -> str:
    text = re.sub(r'\*\*|__|`|#', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower().strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def match_todo_to_plan_item(todo_content: str, plan_items: list) -> int | None:
    best_match = None
    best_score = 0.0
    threshold = 0.6

    for i, item in enumerate(plan_items):
        task = item.get("task", "")
        score = similarity(todo_content, task)

        if normalize_text(task) in normalize_text(todo_content):
            score = max(score, 0.8)
        if normalize_text(todo_content) in normalize_text(task):
            score = max(score, 0.8)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = i

    if best_match is not None:
        log_debug(f"Matched '{todo_content[:50]}' to '{plan_items[best_match]['task'][:50]}' (score: {best_score:.2f})")

    return best_match


def main():
    try:
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            log_debug("Plan verification disabled, skipping todo sync")
            sys.exit(0)

        data = json.load(sys.stdin)

        log_debug(f"Todo sync triggered: {json.dumps(data, indent=2)[:500]}")

        tool_input = data.get("tool_input", {})
        todos = tool_input.get("todos", [])

        if not todos:
            log_debug("No todos in tool input")
            sys.exit(0)

        plan_state = load_plan_state()
        plan_items = plan_state.get("items", [])

        if not plan_items:
            log_debug("No plan items to match against")
            sys.exit(0)

        changes_made = 0

        for todo in todos:
            if todo.get("status") == "completed":
                content = todo.get("content", "")
                match_index = match_todo_to_plan_item(content, plan_items)

                if match_index is not None:
                    if plan_items[match_index].get("status") != "completed":
                        plan_items[match_index]["status"] = "completed"
                        plan_items[match_index]["completed_at"] = datetime.now().isoformat()
                        changes_made += 1
                        log_debug(f"Marked plan item {match_index + 1} as completed: {plan_items[match_index]['task'][:50]}")

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
