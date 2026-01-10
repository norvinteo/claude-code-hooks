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

# Configuration
HOOKS_DIR = Path(__file__).parent
DEBUG_LOG = HOOKS_DIR.parent / "progress/.plan_tracker_debug.log"

# Plan file locations (both user-level and project-level)
PLAN_DIRS = [
    Path.home() / ".claude/plans",  # User-level plans
    HOOKS_DIR.parent / "plans",      # Project-level plans
]


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


def is_plan_file(file_path: str) -> bool:
    """Check if the file is a plan file."""
    path = Path(file_path)
    # Match any .claude/plans/*.json or .claude/plans/*.md file
    # Support both user-level (~/.claude/plans) and project-level (.claude/plans)
    return (
        (".claude/plans" in str(path) or "/plans/" in str(path)) and
        path.suffix in [".json", ".md"]
    )


def parse_json_plan(content: str) -> dict:
    """Parse a JSON plan file."""
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


# Keywords that indicate a section contains template/category items, not actionable tasks
NON_ACTIONABLE_SECTION_KEYWORDS = [
    "template",
    "categories",
    "what to look for",
    "per-module",
    "checklist items",
    "audit each module",
    "performance issues",
    "consistency issues",
    "security issues",
    "maintainability issues",
    "cross-cutting concerns",
    # Also mark audit-style sections as non-actionable
    "shared libraries",
    "shared components",
    "api routes",
    "/lib",
    "/components",
    "/api",
]


def is_non_actionable_section(section: str) -> bool:
    """Check if a section header indicates non-actionable (template/category) items."""
    if not section:
        return False
    section_lower = section.lower()
    return any(keyword in section_lower for keyword in NON_ACTIONABLE_SECTION_KEYWORDS)


def parse_markdown_plan(content: str) -> dict:
    """Parse a Markdown plan file for task items.

    IMPORTANT: Only parses checkbox items (- [ ] or - [x]).
    Numbered lists, headers, and other markdown elements are NOT parsed as tasks.
    This prevents design notes and documentation from being treated as actionable items.

    Items under template/category sections are marked as non-actionable (actionable: false).
    These won't block the stop verifier.
    """
    items = []
    item_id = 0

    # ONLY parse checkbox items - [ ] or - [x] or * [ ] or * [x]
    # Also support - [~] for explicit non-actionable items
    checkbox_pattern = r'^[-*]\s*\[([  xX~])\]\s*(.+)$'

    # Track section headers for context
    header_pattern = r'^###?\s*(.+)$'

    # Track context paragraphs that indicate template sections
    template_context_pattern = r'(?:document findings|for each module|categories|template|what to look for|audit each)'

    lines = content.split('\n')
    current_section = None
    is_template_context = False  # Track if we're in a template context

    for line in lines:
        line = line.strip()

        # Check for section headers (for context, not as tasks)
        header_match = re.match(header_pattern, line)
        if header_match:
            current_section = header_match.group(1).strip()
            # Reset template context when entering a new section
            is_template_context = False
            continue

        # Check for template context indicators in prose
        if re.search(template_context_pattern, line, re.IGNORECASE):
            is_template_context = True

        # ONLY check for checkbox items - these are the actual tasks
        checkbox_match = re.match(checkbox_pattern, line)
        if checkbox_match:
            item_id += 1
            checkbox_char = checkbox_match.group(1).lower()

            # Determine status
            if checkbox_char == 'x':
                status = "completed"
            else:
                status = "pending"

            # Determine if actionable
            # Non-actionable if: explicit [~], template context, or non-actionable section
            is_actionable = (
                checkbox_char != '~' and  # Explicit non-actionable syntax
                not is_template_context and  # Template context detected
                not is_non_actionable_section(current_section)  # Section keywords
            )

            items.append({
                "id": item_id,
                "task": checkbox_match.group(2).strip(),
                "status": status,
                "section": current_section,
                "actionable": is_actionable
            })

    # Extract plan name from first H1 or H2
    name_match = re.search(r'^#\s+(?:Plan:?\s*)?(.+)$', content, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else "Unnamed Plan"

    return {
        "name": name,
        "description": "",
        "items": items,
        "verification": {},
        "format": "markdown"
    }


def load_plan_state(plan_state_file: Path) -> dict:
    """Load existing plan state or return empty state."""
    try:
        if plan_state_file.exists():
            with open(plan_state_file, "r") as f:
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


def save_plan_state(state: dict, plan_state_file: Path):
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


def read_file_content(file_path: str) -> str:
    """Read content of a file."""
    try:
        with open(file_path, "r") as f:
            return f.read()
    except Exception as e:
        log_debug(f"Error reading file {file_path}: {e}")
        return None


def process_plan_file(file_path: str, session_id: str, plan_state_file: Path) -> bool:
    """Process a plan file and update plan state."""
    content = read_file_content(file_path)
    if not content:
        return False

    path = Path(file_path)

    # Parse based on file extension
    if path.suffix == ".json":
        plan_data = parse_json_plan(content)
    else:
        plan_data = parse_markdown_plan(content)

    if not plan_data:
        log_debug(f"Failed to parse plan file: {file_path}")
        return False

    # Load existing state to preserve item statuses if this is an update
    existing_state = load_plan_state(plan_state_file)

    # If same plan file, preserve existing item statuses
    if existing_state.get("plan_file") == file_path:
        existing_items = {item["task"]: item["status"] for item in existing_state.get("items", [])}
        for item in plan_data["items"]:
            if item["task"] in existing_items:
                # Preserve status unless it's explicitly set in the file
                if item.get("status") == "pending" and existing_items[item["task"]] == "completed":
                    item["status"] = "completed"

    # Create new plan state
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

    return save_plan_state(plan_state, plan_state_file)


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


def main():
    """Main entry point for the hook."""
    try:
        # Check if plan verification is enabled (config file OR env var)
        config = load_config()
        env_enabled = os.environ.get("CLAUDE_PLAN_VERIFICATION", "").lower() == "true"
        config_enabled = config.get("plan_verification", False)

        if not (env_enabled or config_enabled):
            # Silently exit if not enabled
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)

        log_debug(f"Received hook data: {json.dumps(data, indent=2)[:500]}")

        # Extract relevant information
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        session_id = data.get("session_id", "")

        # Only process Write or Edit tools
        if tool_name not in ["Write", "Edit"]:
            sys.exit(0)

        # Get the file path from tool input
        file_path = tool_input.get("file_path", "")

        if not file_path:
            log_debug("No file_path in tool input")
            sys.exit(0)

        # Check if this is a plan file
        if not is_plan_file(file_path):
            log_debug(f"Not a plan file: {file_path}")
            sys.exit(0)

        log_debug(f"Processing plan file: {file_path}")

        # Get session-scoped file paths
        plan_state_file, _ = get_session_files(session_id)

        # Process the plan file
        if process_plan_file(file_path, session_id, plan_state_file):
            log_debug(f"Successfully processed plan file: {file_path}")
        else:
            log_debug(f"Failed to process plan file: {file_path}")

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
    except Exception as e:
        log_debug(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
