#!/usr/bin/env python3
"""
Plan Tracker Hook - Captures plans from JSON plan files.

Triggers on: PostToolUse with matcher Write|Edit
Purpose: Track plan files written to .claude/plans/*.json and update plan_state.json
"""

import json
import sys
import os
import re
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.plan_tracker_debug.log")

PLAN_DIRS = [
    Path.home() / ".claude/plans",
    Path("{{PROJECT_DIR}}/.claude/plans"),
]


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def is_plan_file(file_path: str) -> bool:
    path = Path(file_path)
    return (
        (".claude/plans" in str(path) or "/plans/" in str(path)) and
        path.suffix in [".json", ".md"]
    )


def parse_json_plan(content: str) -> dict:
    try:
        plan_data = json.loads(content)
        return {
            "name": plan_data.get("name", "Unnamed Plan"),
            "description": plan_data.get("description", ""),
            "items": plan_data.get("items", []),
            "verification": plan_data.get("verification", {}),
            "format": "json"
        }
    except json.JSONDecodeError as e:
        log_debug(f"JSON parse error: {e}")
        return None


def parse_markdown_plan(content: str) -> dict:
    items = []
    item_id = 0

    checkbox_pattern = r'^[-*]\s*\[([  xX])\]\s*(.+)$'
    header_pattern = r'^###?\s*(.+)$'

    lines = content.split('\n')
    current_section = None

    for line in lines:
        line = line.strip()

        header_match = re.match(header_pattern, line)
        if header_match:
            current_section = header_match.group(1).strip()
            continue

        checkbox_match = re.match(checkbox_pattern, line)
        if checkbox_match:
            item_id += 1
            status = "completed" if checkbox_match.group(1).lower() == 'x' else "pending"
            items.append({
                "id": item_id,
                "task": checkbox_match.group(2).strip(),
                "status": status,
                "section": current_section
            })

    name_match = re.search(r'^#\s+(?:Plan:?\s*)?(.+)$', content, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else "Unnamed Plan"

    return {
        "name": name,
        "description": "",
        "items": items,
        "verification": {},
        "format": "markdown"
    }


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            with open(PLAN_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")

    return {
        "session_id": None,
        "plan_source": None,
        "plan_file": None,
        "items": [],
        "created_at": None,
        "updated_at": None
    }


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


def read_file_content(file_path: str) -> str:
    try:
        with open(file_path, "r") as f:
            return f.read()
    except Exception as e:
        log_debug(f"Error reading file {file_path}: {e}")
        return None


def process_plan_file(file_path: str, session_id: str) -> bool:
    content = read_file_content(file_path)
    if not content:
        return False

    path = Path(file_path)

    if path.suffix == ".json":
        plan_data = parse_json_plan(content)
    else:
        plan_data = parse_markdown_plan(content)

    if not plan_data:
        log_debug(f"Failed to parse plan file: {file_path}")
        return False

    existing_state = load_plan_state()

    if existing_state.get("plan_file") == file_path:
        existing_items = {item["task"]: item["status"] for item in existing_state.get("items", [])}
        for item in plan_data["items"]:
            if item["task"] in existing_items:
                if item.get("status") == "pending" and existing_items[item["task"]] == "completed":
                    item["status"] = "completed"

    plan_state = {
        "session_id": session_id,
        "plan_source": "file",
        "plan_file": file_path,
        "name": plan_data.get("name", "Unnamed Plan"),
        "description": plan_data.get("description", ""),
        "items": plan_data.get("items", []),
        "verification": plan_data.get("verification", {}),
        "format": plan_data.get("format", "unknown"),
        "created_at": existing_state.get("created_at") or datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }

    return save_plan_state(plan_state)


def load_config() -> dict:
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def main():
    try:
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            sys.exit(0)

        data = json.load(sys.stdin)

        log_debug(f"Received hook data: {json.dumps(data, indent=2)[:500]}")

        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        session_id = data.get("session_id", "")

        if tool_name not in ["Write", "Edit"]:
            sys.exit(0)

        file_path = tool_input.get("file_path", "")

        if not file_path:
            log_debug("No file_path in tool input")
            sys.exit(0)

        if not is_plan_file(file_path):
            log_debug(f"Not a plan file: {file_path}")
            sys.exit(0)

        log_debug(f"Processing plan file: {file_path}")

        if process_plan_file(file_path, session_id):
            log_debug(f"Successfully processed plan file: {file_path}")
        else:
            log_debug(f"Failed to process plan file: {file_path}")

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
    except Exception as e:
        log_debug(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
