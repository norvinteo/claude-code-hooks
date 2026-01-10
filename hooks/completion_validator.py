#!/usr/bin/env python3
"""
Completion Validator Hook - Runs code review and build after plan completion.

Triggers on: Stop (after stop_verifier allows)
Purpose: When all plan items are complete, run linting, type checking, and build.

If issues are found:
- Block the stop
- Report the issues
- Add fix tasks to plan_state

Config options in config.json:
- auto_code_review: true/false - Enable this hook
- validation_commands: list of commands to run
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

# Configuration
HOOKS_DIR = Path(__file__).parent
PROJECT_DIR = HOOKS_DIR.parent.parent  # Assumes hooks are in .claude/hooks/
DEBUG_LOG = HOOKS_DIR.parent / "progress/.completion_validator_debug.log"
VALIDATION_LOG = HOOKS_DIR.parent / "progress/validation_results.log"


def get_session_files(session_id: str) -> tuple:
    """Get session-scoped file paths."""
    sessions_dir = HOOKS_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    plan_state_file = sessions_dir / f"{session_id}_plan_state.json"
    stop_attempts_file = sessions_dir / f"{session_id}_stop_attempts.json"

    return plan_state_file, stop_attempts_file

# Default validation commands
DEFAULT_VALIDATIONS = [
    {
        "name": "TypeScript Check",
        "command": "npm run tsc --noEmit",
        "timeout": 120,
        "required": True
    },
    {
        "name": "ESLint",
        "command": "npm run lint",
        "timeout": 60,
        "required": False  # Warnings OK
    },
    {
        "name": "Build",
        "command": "npm run build",
        "timeout": 300,
        "required": True
    }
]


def log_debug(message: str):
    """Log debug message to file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def log_validation(message: str):
    """Log validation results."""
    try:
        VALIDATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VALIDATION_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_config() -> dict:
    """Load config from file."""
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            return json.loads(config_file.read_text())
    except Exception:
        pass
    return {}


def load_plan_state(plan_state_file: Path) -> dict:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            return json.loads(plan_state_file.read_text())
    except Exception:
        pass
    return None


def save_plan_state(state: dict, plan_state_file: Path):
    """Save plan state to file."""
    try:
        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()
        plan_state_file.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")


def has_incomplete_items(plan_state: dict) -> bool:
    """Check if plan has incomplete items."""
    if not plan_state or not plan_state.get("items"):
        return False
    for item in plan_state.get("items", []):
        if item.get("status") not in ["completed", "done"]:
            return True
    return False


def run_validation(validation: dict) -> dict:
    """Run a single validation command."""
    name = validation.get("name", "Unknown")
    command = validation.get("command", "")
    timeout = validation.get("timeout", 60)
    required = validation.get("required", True)

    log_debug(f"Running validation: {name}")

    result = {
        "name": name,
        "command": command,
        "success": False,
        "required": required,
        "output": "",
        "error": ""
    }

    try:
        process = subprocess.run(
            command,
            shell=True,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        result["success"] = process.returncode == 0
        result["output"] = process.stdout[-2000:] if process.stdout else ""  # Last 2000 chars
        result["error"] = process.stderr[-2000:] if process.stderr else ""
        result["returncode"] = process.returncode

        log_debug(f"{name}: {'PASS' if result['success'] else 'FAIL'} (code: {process.returncode})")

    except subprocess.TimeoutExpired:
        result["error"] = f"Timeout after {timeout}s"
        log_debug(f"{name}: TIMEOUT")
    except Exception as e:
        result["error"] = str(e)
        log_debug(f"{name}: ERROR - {e}")

    return result


def extract_errors(output: str, error: str) -> list:
    """Extract error messages from command output."""
    errors = []
    combined = (output + "\n" + error).strip()

    # Look for common error patterns
    for line in combined.split("\n"):
        line = line.strip()
        if not line:
            continue

        # TypeScript errors
        if "error TS" in line or ": error:" in line.lower():
            errors.append(line[:200])

        # ESLint errors
        elif "error" in line.lower() and (":" in line or "✖" in line):
            errors.append(line[:200])

        # Build errors
        elif "Error:" in line or "error:" in line:
            errors.append(line[:200])

    # Deduplicate and limit
    seen = set()
    unique_errors = []
    for err in errors:
        if err not in seen:
            seen.add(err)
            unique_errors.append(err)
            if len(unique_errors) >= 10:
                break

    return unique_errors


def add_fix_tasks_to_plan(plan_state: dict, errors: list, validation_name: str) -> dict:
    """Add fix tasks to plan state."""
    if not plan_state:
        plan_state = {"items": []}

    items = plan_state.get("items", [])
    max_id = max([i.get("id", 0) for i in items], default=0)

    # Add a single fix task for this validation
    max_id += 1
    fix_task = {
        "id": max_id,
        "task": f"Fix {validation_name} errors ({len(errors)} issues)",
        "status": "pending",
        "added_by": "completion_validator",
        "errors": errors[:5],  # Include first 5 errors for context
        "created_at": datetime.now().isoformat()
    }
    items.append(fix_task)

    plan_state["items"] = items
    plan_state["validation_failed"] = True
    return plan_state


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    """Main entry point for the hook."""
    try:
        # Check if auto code review is enabled
        config = load_config()
        if not config.get("auto_code_review", False):
            log_debug("Auto code review disabled")
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "default")

        log_debug(f"Completion validator triggered for session: {session_id}")

        # Get session-scoped file paths
        plan_state_file, _ = get_session_files(session_id)

        # Load plan state
        plan_state = load_plan_state(plan_state_file)

        # Only run validation if all items were complete (stop_verifier allowed)
        # Check for validation_failed flag to avoid re-running after adding fix tasks
        if plan_state and plan_state.get("validation_failed"):
            log_debug("Validation already failed, skipping re-run")
            output_hook_response(True)
            sys.exit(0)

        # If there are incomplete items, stop_verifier should have blocked
        # This hook only runs when stop is allowed
        if has_incomplete_items(plan_state):
            log_debug("Has incomplete items, stop_verifier should handle this")
            output_hook_response(True)
            sys.exit(0)

        # Get validation commands from config or use defaults
        validations = config.get("validation_commands", DEFAULT_VALIDATIONS)

        log_debug(f"Running {len(validations)} validations")
        log_validation(f"=== Validation Run for session {session_id} ===")

        all_passed = True
        failed_validations = []
        all_errors = []

        for validation in validations:
            result = run_validation(validation)

            status = "✅ PASS" if result["success"] else "❌ FAIL"
            log_validation(f"{result['name']}: {status}")

            if not result["success"]:
                if result["required"]:
                    all_passed = False
                    failed_validations.append(result["name"])

                # Extract specific errors
                errors = extract_errors(result["output"], result["error"])
                if errors:
                    all_errors.extend([(result["name"], err) for err in errors])
                    log_validation(f"  Errors: {len(errors)} found")
                    for err in errors[:3]:
                        log_validation(f"    - {err[:100]}")

        if all_passed:
            log_debug("All validations passed!")
            log_validation("=== All validations PASSED ===\n")
            output_hook_response(
                True,
                f"✅ Validation complete: All checks passed!\n"
                f"  • TypeScript: OK\n"
                f"  • Lint: OK\n"
                f"  • Build: OK"
            )
        else:
            log_debug(f"Validations failed: {failed_validations}")
            log_validation(f"=== Validation FAILED: {failed_validations} ===\n")

            # Add fix tasks to plan
            if plan_state:
                for name, err in all_errors[:5]:  # First 5 unique errors
                    plan_state = add_fix_tasks_to_plan(plan_state, [err], name)
                save_plan_state(plan_state, plan_state_file)

            # Build error summary
            error_summary = "\n".join([f"  • {err[:80]}" for _, err in all_errors[:5]])
            if len(all_errors) > 5:
                error_summary += f"\n  ... and {len(all_errors) - 5} more errors"

            output_hook_response(
                False,  # Block the stop
                f"❌ Validation FAILED: {', '.join(failed_validations)}\n\n"
                f"Errors found:\n{error_summary}\n\n"
                f"👉 Fix these issues before stopping."
            )

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        # Don't block on validator errors
        output_hook_response(True, f"⚠️ Validation skipped due to error: {str(e)[:100]}")


if __name__ == "__main__":
    main()
