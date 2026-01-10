#!/usr/bin/env python3
"""
Todo Sync Hook - Syncs TodoWrite completions to plan_state.json.

Triggers on: PostToolUse with matcher "TodoWrite"
Purpose: Match completed todos to plan items using smart keyword matching
         (No API calls - works with Claude subscription)
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.todo_sync_debug.log")

# Stop words to filter out when extracting keywords
STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just", "and",
    "but", "if", "or", "because", "until", "while", "this", "that", "these",
    "those", "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their", "what", "which", "who"
}

# Synonym mappings for common action words
SYNONYMS = {
    "create": ["add", "make", "build", "implement", "set up", "setup", "write"],
    "update": ["modify", "change", "edit", "revise", "fix", "adjust"],
    "delete": ["remove", "drop", "clear", "clean"],
    "complete": ["finish", "done", "completed", "finalize"],
    "push": ["upload", "deploy", "publish", "commit"],
    "repository": ["repo", "github", "git"],
    "install": ["setup", "set up", "configure", "initialize", "init"],
    "test": ["verify", "check", "validate", "run tests"],
}


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


def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text, filtering stop words."""
    # Normalize: lowercase, replace punctuation with spaces
    normalized = re.sub(r'[^\w\s]', ' ', text.lower())
    words = normalized.split()

    # Filter stop words and short words
    keywords = {w for w in words if w not in STOP_WORDS and len(w) > 2}
    return keywords


def expand_with_synonyms(keywords: set) -> set:
    """Expand keywords with their synonyms."""
    expanded = set(keywords)
    for word in keywords:
        # Check if word is a key in synonyms
        if word in SYNONYMS:
            expanded.update(SYNONYMS[word])
        # Check if word is a value in synonyms
        for key, values in SYNONYMS.items():
            if word in values:
                expanded.add(key)
                expanded.update(values)
    return expanded


def smart_match(todo_content: str, plan_items: list) -> int | None:
    """Match todo to plan item using keyword overlap with synonym expansion."""

    # Filter to only pending items
    pending_items = [
        (i, item) for i, item in enumerate(plan_items)
        if item.get("status") != "completed"
    ]

    if not pending_items:
        log_debug("No pending plan items to match against")
        return None

    # Extract and expand todo keywords
    todo_keywords = extract_keywords(todo_content)
    todo_expanded = expand_with_synonyms(todo_keywords)

    log_debug(f"Todo keywords: {todo_keywords}")
    log_debug(f"Todo expanded: {todo_expanded}")

    best_match = None
    best_score = 0.0
    threshold = 0.3  # Minimum overlap ratio to consider a match

    for orig_idx, item in pending_items:
        task = item.get("task", "")

        # Extract and expand plan item keywords
        plan_keywords = extract_keywords(task)
        plan_expanded = expand_with_synonyms(plan_keywords)

        # Calculate overlap score
        if not plan_expanded or not todo_expanded:
            continue

        # Jaccard-like similarity: intersection / union
        intersection = todo_expanded & plan_expanded
        union = todo_expanded | plan_expanded

        if union:
            score = len(intersection) / len(union)

            # Bonus: if all plan keywords are in todo (task completed)
            if plan_keywords and plan_keywords.issubset(todo_expanded):
                score += 0.2

            log_debug(f"Match score for '{task[:40]}': {score:.2f} (overlap: {intersection})")

            if score > best_score and score >= threshold:
                best_score = score
                best_match = orig_idx

    if best_match is not None:
        log_debug(f"Best match: index {best_match} with score {best_score:.2f}")
    else:
        log_debug("No match found above threshold")

    return best_match


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
                    # No exact match - try smart keyword matching on completed todos
                    if status == "completed":
                        match_index = smart_match(content, plan_items)
                        if match_index is not None:
                            if plan_items[match_index].get("status") != "completed":
                                plan_items[match_index]["status"] = "completed"
                                plan_items[match_index]["completed_at"] = datetime.now().isoformat()
                                changes_made += 1
                                log_debug(f"Smart match - marked complete: {plan_items[match_index]['task'][:50]}")
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
