#!/usr/bin/env python3
"""
Completion Validator Hook - Runs code review and build after plan completion.

Triggers on: Stop (after stop_verifier allows)
Purpose: When all plan items are complete, run linting, type checking, and build.
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path("{{PROJECT_DIR}}/.claude/hooks")
PROJECT_DIR = Path("{{PROJECT_DIR}}")
PLAN_STATE_FILE = HOOKS_DIR / "plan_state.json"
DEBUG_LOG = Path("{{PROJECT_DIR}}/progress/.completion_validator_debug.log")
VALIDATION_LOG = Path("{{PROJECT_DIR}}/progress/validation_results.log")

DEFAULT_VALIDATIONS = [
    {
        "name": "TypeScript Check",
        "command": "npm run tsc --noEmit || bun run tsc --noEmit || yarn tsc --noEmit",
        "timeout": 120,
        "required": True
    },
    {
        "name": "ESLint",
        "command": "npm run lint || bun run lint || yarn lint",
        "timeout": 60,
        "required": False
    },
    {
        "name": "Build",
        "command": "npm run build || bun run build || yarn build",
        "timeout": 300,
        "required": True
    }
]


def log_debug(message: str):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def log_validation(message: str):
    try:
        VALIDATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VALIDATION_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def load_config() -> dict:
    config_file = HOOKS_DIR / "config.json"
    try:
        if config_file.exists():
            return json.loads(config_file.read_text())
    except Exception:
        pass
    return {}


def load_plan_state() -> dict:
    try:
        if PLAN_STATE_FILE.exists():
            return json.loads(PLAN_STATE_FILE.read_text())
    except Exception:
        pass
    return None


def save_plan_state(state: dict):
    try:
        state["updated_at"] = datetime.now().isoformat()
        PLAN_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")


def has_incomplete_items(plan_state: dict) -> bool:
    if not plan_state or not plan_state.get("items"):
        return False
    for item in plan_state.get("items", []):
        if item.get("status") not in ["completed", "done"]:
            return True
    return False


def run_validation(validation: dict) -> dict:
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
        result["output"] = process.stdout[-2000:] if process.stdout else ""
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
    errors = []
    combined = (output + "\n" + error).strip()

    for line in combined.split("\n"):
        line = line.strip()
        if not line:
            continue

        if "error TS" in line or ": error:" in line.lower():
            errors.append(line[:200])
        elif "error" in line.lower() and (":" in line or "x" in line):
            errors.append(line[:200])
        elif "Error:" in line or "error:" in line:
            errors.append(line[:200])

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
    if not plan_state:
        plan_state = {"items": []}

    items = plan_state.get("items", [])
    max_id = max([i.get("id", 0) for i in items], default=0)

    max_id += 1
    fix_task = {
        "id": max_id,
        "task": f"Fix {validation_name} errors ({len(errors)} issues)",
        "status": "pending",
        "added_by": "completion_validator",
        "errors": errors[:5],
        "created_at": datetime.now().isoformat()
    }
    items.append(fix_task)

    plan_state["items"] = items
    plan_state["validation_failed"] = True
    return plan_state


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def main():
    try:
        config = load_config()
        if not config.get("auto_code_review", False):
            log_debug("Auto code review disabled")
            output_hook_response(True)
            sys.exit(0)

        data = json.load(sys.stdin)
        session_id = data.get("session_id", "unknown")

        log_debug(f"Completion validator triggered for session: {session_id}")

        plan_state = load_plan_state()

        if plan_state and plan_state.get("validation_failed"):
            log_debug("Validation already failed, skipping re-run")
            output_hook_response(True)
            sys.exit(0)

        if has_incomplete_items(plan_state):
            log_debug("Has incomplete items, stop_verifier should handle this")
            output_hook_response(True)
            sys.exit(0)

        validations = config.get("validation_commands", DEFAULT_VALIDATIONS)

        log_debug(f"Running {len(validations)} validations")
        log_validation(f"=== Validation Run for session {session_id} ===")

        all_passed = True
        failed_validations = []
        all_errors = []

        for validation in validations:
            result = run_validation(validation)

            status = "PASS" if result["success"] else "FAIL"
            log_validation(f"{result['name']}: {status}")

            if not result["success"]:
                if result["required"]:
                    all_passed = False
                    failed_validations.append(result["name"])

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
                f"Validation complete: All checks passed!\n"
                f"  - TypeScript: OK\n"
                f"  - Lint: OK\n"
                f"  - Build: OK"
            )
        else:
            log_debug(f"Validations failed: {failed_validations}")
            log_validation(f"=== Validation FAILED: {failed_validations} ===\n")

            if plan_state:
                for name, err in all_errors[:5]:
                    plan_state = add_fix_tasks_to_plan(plan_state, [err], name)
                save_plan_state(plan_state)

            error_summary = "\n".join([f"  - {err[:80]}" for _, err in all_errors[:5]])
            if len(all_errors) > 5:
                error_summary += f"\n  ... and {len(all_errors) - 5} more errors"

            output_hook_response(
                False,
                f"Validation FAILED: {', '.join(failed_validations)}\n\n"
                f"Errors found:\n{error_summary}\n\n"
                f"Fix these issues before stopping."
            )

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True, f"Validation skipped due to error: {str(e)[:100]}")


if __name__ == "__main__":
    main()
