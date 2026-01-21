#!/usr/bin/env python3
"""
Todo Sync Hook - Syncs TodoWrite completions to plan_state.json.

Triggers on: PostToolUse with matcher "TodoWrite"
Purpose: Match completed todos to plan items using smart keyword matching
         (No API calls - works with Claude subscription)

Enhanced with:
- Incremental validation: Run quick lint/type check when tasks complete
- File change tracking: Track which files were modified during the session
- Early warning: Alert Claude to errors while context is fresh
"""

import json
import sys
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration - use relative paths for portability
HOOKS_DIR = Path(__file__).parent
PROJECT_DIR = HOOKS_DIR.parent.parent  # .claude/hooks -> .claude -> project root
DEBUG_LOG = PROJECT_DIR / "progress/.todo_sync_debug.log"

# Import shared helper for cross-session plan tracking
try:
    from plan_session_helper import load_plan_state_with_fallback, save_active_plan
    HAS_HELPER = True
except ImportError:
    HAS_HELPER = False

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
    "authentication": ["auth", "login", "signin", "sign-in"],
}


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


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            with open(plan_state_file, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return {"items": []}


def save_plan_state(state: dict, plan_state_file: Path) -> bool:
    """Save plan state to file."""
    try:
        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()

        with open(plan_state_file, "w") as f:
            json.dump(state, f, indent=2)

        log_debug(f"Saved plan state to {plan_state_file.name}: {len(state.get('items', []))} items")
        return True
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")
        return False


def get_recent_file_changes() -> list:
    """Get list of recently modified files using git."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        # Also check staged changes
        result_staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result_staged.returncode == 0 and result_staged.stdout.strip():
            return [f.strip() for f in result_staged.stdout.strip().split("\n") if f.strip()]

    except Exception as e:
        log_debug(f"Error getting file changes: {e}")

    return []


def run_quick_validation(files: list) -> tuple:
    """Run quick TypeScript check on recently changed files.

    Returns:
        tuple: (success: bool, errors: list)
    """
    if not files:
        return True, []

    # Filter to TypeScript/JavaScript files
    ts_files = [f for f in files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]

    if not ts_files:
        return True, []

    # Limit to 10 files
    ts_files = ts_files[:10]

    try:
        # Quick type check
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--pretty", "false"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            return True, []

        # Extract error messages
        errors = []
        for line in (result.stdout + "\n" + result.stderr).split("\n"):
            line = line.strip()
            if "error TS" in line or ": error:" in line.lower():
                errors.append(line[:150])
                if len(errors) >= 5:
                    break

        return False, errors

    except subprocess.TimeoutExpired:
        log_debug("Quick validation timed out")
        return True, []
    except Exception as e:
        log_debug(f"Error in quick validation: {e}")
        return True, []


def track_session_file_changes(session_id: str):
    """Track file changes for this session."""
    sessions_dir = HOOKS_DIR / "sessions"
    changes_file = sessions_dir / f"{session_id}_file_changes.json"

    try:
        # Load existing tracked files
        existing = set()
        if changes_file.exists():
            data = json.loads(changes_file.read_text())
            existing = set(data.get("files", []))

        # Get current git changes
        current = set(get_recent_file_changes())

        # Merge and save
        all_files = existing | current
        changes_file.write_text(json.dumps({
            "files": list(all_files),
            "updated_at": datetime.now().isoformat()
        }, indent=2))

    except Exception as e:
        log_debug(f"Error tracking file changes: {e}")


def stem_word(word: str) -> str:
    """Simple stemming - remove common suffixes."""
    if len(word) >= 5:
        if word.endswith('ing'):
            return word[:-3]
        if word.endswith('ied'):
            return word[:-3] + 'y'  # verified -> verify
        if word.endswith('ed'):
            if word[-3] == word[-4]:  # doubled consonant: stopped -> stop
                return word[:-3]
            return word[:-2] if not word.endswith('eed') else word[:-1]
        if word.endswith('tion'):
            return word[:-4] + 'te'  # authentication -> authenticate
        if word.endswith('ated'):
            return word[:-1]  # created -> create
    return word


def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text, filtering stop words."""
    # Normalize: lowercase, replace punctuation with spaces
    normalized = re.sub(r'[^\w\s]', ' ', text.lower())
    words = normalized.split()

    # Filter stop words and short words, apply stemming
    keywords = set()
    for w in words:
        if w not in STOP_WORDS and len(w) > 2:
            keywords.add(w)
            stemmed = stem_word(w)
            if stemmed != w and len(stemmed) > 2:
                keywords.add(stemmed)
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
    threshold = 0.25  # Minimum overlap ratio to consider a match

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
        session_id = data.get("session_id", "default")

        log_debug(f"Session {session_id}: Todo sync triggered")

        # Extract todos from tool input
        tool_input = data.get("tool_input", {})
        todos = tool_input.get("todos", [])

        if not todos:
            log_debug("No todos in tool input")
            sys.exit(0)

        # Load plan state with fallback to active plan from other sessions
        if HAS_HELPER:
            plan_state, plan_state_file, is_fallback = load_plan_state_with_fallback(session_id)
            if is_fallback:
                log_debug(f"Session {session_id}: Using fallback plan from {plan_state.get('session_id')}")
        else:
            plan_state_file, _ = get_session_files(session_id)
            plan_state = load_plan_state(plan_state_file)

        # Check if there's an active plan
        if not plan_state:
            log_debug(f"Session {session_id}: No active plan, skipping todo sync")
            sys.exit(0)

        plan_items = plan_state.get("items", [])
        has_active_plan = plan_state.get("name") or plan_state.get("session_id")

        if not has_active_plan:
            log_debug(f"Session {session_id}: No active plan, skipping todo sync")
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
            save_plan_state(plan_state, plan_state_file)
            log_debug(f"Session {session_id}: Updated plan: {changes_made} changes made")

            # Track file changes for this session
            track_session_file_changes(session_id)

            # Run incremental validation if tasks were completed
            completed_count = sum(1 for t in todos if t.get("status") == "completed")
            if completed_count > 0 and config.get("incremental_validation", True):
                log_debug(f"Running incremental validation after {completed_count} task(s) completed")

                changed_files = get_recent_file_changes()
                if changed_files:
                    success, errors = run_quick_validation(changed_files)

                    if not success and errors:
                        # Output warning (not blocking, just informative)
                        error_text = "\n".join([f"  - {e}" for e in errors[:3]])
                        warning_msg = (
                            f"⚠️ **Validation Warning**: Task marked complete but errors detected:\n"
                            f"{error_text}\n\n"
                            f"Consider fixing these before continuing."
                        )
                        # Write to a session warning file for other hooks to pick up
                        warnings_file = HOOKS_DIR / "sessions" / f"{session_id}_warnings.json"
                        try:
                            warnings_file.write_text(json.dumps({
                                "message": warning_msg,
                                "errors": errors,
                                "timestamp": datetime.now().isoformat()
                            }, indent=2))
                        except Exception:
                            pass
                        log_debug(f"Validation found {len(errors)} errors after task completion")
        else:
            log_debug(f"Session {session_id}: No changes to plan")

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
    except Exception as e:
        log_debug(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
