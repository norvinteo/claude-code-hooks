#!/usr/bin/env python3
"""
AI Task Verifier Hook - Uses Claude API to verify task completion quality.

Triggers on: Stop (after completion_validator passes)
Purpose: Verify that Claude actually completed each task correctly, not just marked them done.

Verification Checks:
1. GAPS: Did Claude miss anything from the plan?
2. MISMATCHES: Does the implementation match what was requested?

Config options in config.json:
- ai_verification: true/false - Enable this hook (default: false)
- ai_verification_model: "haiku" | "sonnet" - Model to use (default: haiku)
- ai_verification_threshold: 0-100 - Minimum confidence to pass (default: 70)
- ai_verification_sample_rate: 0.0-1.0 - Probability of running (default: 1.0)

Requires: ANTHROPIC_API_KEY environment variable
"""

import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Configuration - paths relative to this script
HOOKS_DIR = Path(__file__).parent
PROJECT_ROOT = HOOKS_DIR.parent.parent  # .claude/hooks -> .claude -> project
DEBUG_LOG = PROJECT_ROOT / "progress" / ".ai_verifier_debug.log"
VERIFICATION_LOG = PROJECT_ROOT / "progress" / "ai_verification_results.log"

# Model configurations
MODELS = {
    "haiku": "claude-3-5-haiku-20241022",
    "sonnet": "claude-sonnet-4-20250514",
}

VERIFICATION_PROMPT = """You are a code review assistant verifying task completion.

## Original Plan
{plan_content}

## Tasks Marked as Complete
{completed_tasks}

## Code Changes Made (git diff)
```diff
{git_diff}
```

## Your Task
Analyze if the implementation matches the plan requirements:

1. **GAPS**: List any tasks or subtasks from the plan that were NOT implemented or are incomplete.
2. **MISMATCHES**: List any differences between what was requested and what was built.
3. For each issue, rate severity: "critical" (blocks functionality), "warning" (suboptimal), or "minor" (cosmetic/cleanup)

## Output Format (JSON only)
Return ONLY valid JSON with no additional text:
{{
  "gaps": [
    {{"description": "Description of what was missed", "severity": "critical|warning|minor"}}
  ],
  "mismatches": [
    {{"expected": "What the plan requested", "actual": "What was implemented", "severity": "critical|warning|minor"}}
  ],
  "confidence": 0-100,
  "passed": true/false,
  "summary": "One sentence summary of verification result"
}}

Rules:
- passed=true if no critical issues AND confidence >= {threshold}
- Empty arrays for gaps/mismatches if none found
- Be strict but fair - only flag real issues, not style preferences
- confidence reflects how certain you are about your assessment
"""


def log_debug(message: str):
    """Log debug message to file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception:
        pass


def log_verification(message: str):
    """Log verification results."""
    try:
        VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATION_LOG, "a") as f:
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


def get_session_files(session_id: str) -> Path:
    """Get session-scoped file paths."""
    sessions_dir = HOOKS_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    plan_state_file = sessions_dir / f"{session_id}_plan_state.json"
    return plan_state_file


def load_plan_state(plan_state_file: Path) -> dict | None:
    """Load plan state from file."""
    try:
        if plan_state_file.exists():
            return json.loads(plan_state_file.read_text())
    except Exception as e:
        log_debug(f"Error loading plan state: {e}")
    return None


def save_plan_state(state: dict, plan_state_file: Path):
    """Save plan state to file."""
    try:
        plan_state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = datetime.now().isoformat()
        plan_state_file.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log_debug(f"Error saving plan state: {e}")


def get_git_diff() -> str:
    """Get git diff of changes in the working directory."""
    try:
        # Get both staged and unstaged changes
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )
        diff = result.stdout

        # Truncate if too long (keep first 8000 chars)
        if len(diff) > 8000:
            diff = diff[:8000] + "\n... (diff truncated, too large)"

        return diff or "(No changes detected)"
    except Exception as e:
        log_debug(f"Error getting git diff: {e}")
        return "(Error getting diff)"


def get_completed_tasks(plan_state: dict) -> str:
    """Format completed tasks for the prompt."""
    if not plan_state or "items" not in plan_state:
        return "(No tasks found)"

    completed = []
    for item in plan_state.get("items", []):
        if item.get("status") in ["completed", "done"]:
            task = item.get("task", "Unknown task")
            completed.append(f"- [x] {task}")

    return "\n".join(completed) if completed else "(No tasks marked complete)"


def get_plan_content(plan_state: dict) -> str:
    """Get the original plan content."""
    # First try to get from plan_file reference
    plan_file = plan_state.get("plan_file")
    if plan_file and Path(plan_file).exists():
        try:
            return Path(plan_file).read_text()[:4000]  # Limit size
        except Exception:
            pass

    # Fall back to reconstructing from items
    items = plan_state.get("items", [])
    if items:
        lines = [f"# {plan_state.get('name', 'Plan')}"]
        for item in items:
            status_mark = "[x]" if item.get("status") in ["completed", "done"] else "[ ]"
            lines.append(f"- {status_mark} {item.get('task', 'Unknown')}")
        return "\n".join(lines)

    return "(No plan content available)"


def call_claude_api(prompt: str, model: str) -> dict | None:
    """Call Claude API for verification."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log_debug("ANTHROPIC_API_KEY not set")
        return None

    try:
        import urllib.request
        import urllib.error

        model_id = MODELS.get(model, MODELS["haiku"])

        request_data = {
            "model": model_id,
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(request_data).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        log_debug(f"Calling Claude API with model: {model_id}")

        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))

        # Extract text content
        if "content" in result and len(result["content"]) > 0:
            text = result["content"][0].get("text", "")
            log_debug(f"API response: {text[:500]}")

            # Parse JSON from response
            try:
                json_start = text.find("{")
                json_end = text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = text[json_start:json_end]
                    return json.loads(json_str)
            except json.JSONDecodeError as e:
                log_debug(f"Error parsing API response JSON: {e}")

        return None

    except urllib.error.HTTPError as e:
        log_debug(f"HTTP error calling Claude API: {e.code} - {e.read().decode()}")
        return None
    except Exception as e:
        log_debug(f"Error calling Claude API: {e}")
        return None


def add_remediation_tasks(plan_state: dict, verification_result: dict) -> dict:
    """Add remediation tasks to plan state based on verification results."""
    if not plan_state:
        plan_state = {"items": []}

    items = plan_state.get("items", [])
    max_id = max([i.get("id", 0) for i in items], default=0)

    # Add tasks for gaps
    for gap in verification_result.get("gaps", []):
        if gap.get("severity") in ["critical", "warning"]:
            max_id += 1
            items.append({
                "id": max_id,
                "task": f"[AI REVIEW] {gap.get('description', 'Fix missing implementation')}",
                "status": "pending",
                "added_by": "ai_task_verifier",
                "severity": gap.get("severity"),
                "created_at": datetime.now().isoformat()
            })

    # Add tasks for mismatches
    for mismatch in verification_result.get("mismatches", []):
        if mismatch.get("severity") in ["critical", "warning"]:
            max_id += 1
            expected = mismatch.get("expected", "")[:100]
            actual = mismatch.get("actual", "")[:100]
            items.append({
                "id": max_id,
                "task": f"[AI REVIEW] Fix: expected '{expected}' but got '{actual}'",
                "status": "pending",
                "added_by": "ai_task_verifier",
                "severity": mismatch.get("severity"),
                "created_at": datetime.now().isoformat()
            })

    plan_state["items"] = items
    plan_state["verification"] = {
        "verified_at": datetime.now().isoformat(),
        "passed": verification_result.get("passed", False),
        "gaps": verification_result.get("gaps", []),
        "mismatches": verification_result.get("mismatches", []),
        "confidence": verification_result.get("confidence", 0),
        "summary": verification_result.get("summary", "")
    }

    return plan_state


def output_hook_response(continue_execution: bool = True, system_message: str = None):
    """Output JSON response for hook system."""
    response = {"continue": continue_execution}
    if system_message:
        response["systemMessage"] = system_message
    print(json.dumps(response))


def has_incomplete_items(plan_state: dict) -> bool:
    """Check if plan has incomplete items."""
    if not plan_state or not plan_state.get("items"):
        return False
    for item in plan_state.get("items", []):
        if item.get("actionable") is False:
            continue
        if item.get("status") not in ["completed", "done"]:
            return True
    return False


def main():
    """Main entry point for the hook."""
    try:
        config = load_config()

        # Check if AI verification is enabled (disabled by default)
        if not config.get("ai_verification", False):
            log_debug("AI verification disabled")
            output_hook_response(True)
            sys.exit(0)

        # Sample rate check (for cost control)
        sample_rate = config.get("ai_verification_sample_rate", 1.0)
        if random.random() > sample_rate:
            log_debug(f"Skipped by sample rate ({sample_rate})")
            output_hook_response(True)
            sys.exit(0)

        # Read JSON input from stdin
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "default")

        log_debug(f"AI task verifier triggered for session: {session_id}")

        # Get plan state
        plan_state_file = get_session_files(session_id)
        plan_state = load_plan_state(plan_state_file)

        # Skip if no plan or has incomplete items
        if not plan_state or has_incomplete_items(plan_state):
            log_debug("No plan or incomplete items, skipping AI verification")
            output_hook_response(True)
            sys.exit(0)

        # Skip if already verified
        if plan_state.get("verification", {}).get("passed"):
            log_debug("Already verified and passed")
            output_hook_response(True)
            sys.exit(0)

        # Skip if validation already failed
        if plan_state.get("validation_failed"):
            log_debug("Validation failed, skipping AI verification")
            output_hook_response(True)
            sys.exit(0)

        # Gather context for verification
        plan_content = get_plan_content(plan_state)
        completed_tasks = get_completed_tasks(plan_state)
        git_diff = get_git_diff()

        # Get config values
        model = config.get("ai_verification_model", "haiku")
        threshold = config.get("ai_verification_threshold", 70)

        # Build verification prompt
        prompt = VERIFICATION_PROMPT.format(
            plan_content=plan_content,
            completed_tasks=completed_tasks,
            git_diff=git_diff,
            threshold=threshold
        )

        log_debug(f"Verification prompt length: {len(prompt)}")
        log_verification(f"=== AI Verification for session {session_id} ===")

        # Call Claude API
        result = call_claude_api(prompt, model)

        if not result:
            log_debug("No response from Claude API, allowing stop")
            log_verification("AI verification skipped - no API response")
            output_hook_response(True, "⚠️ AI verification skipped (API unavailable)")
            sys.exit(0)

        # Process results
        passed = result.get("passed", True)
        confidence = result.get("confidence", 100)
        gaps = result.get("gaps", [])
        mismatches = result.get("mismatches", [])
        summary = result.get("summary", "Verification complete")

        # Count critical/warning issues
        critical_gaps = [g for g in gaps if g.get("severity") == "critical"]
        critical_mismatches = [m for m in mismatches if m.get("severity") == "critical"]
        warning_gaps = [g for g in gaps if g.get("severity") == "warning"]
        warning_mismatches = [m for m in mismatches if m.get("severity") == "warning"]

        log_verification(f"Passed: {passed}, Confidence: {confidence}")
        log_verification(f"Gaps: {len(gaps)} ({len(critical_gaps)} critical)")
        log_verification(f"Mismatches: {len(mismatches)} ({len(critical_mismatches)} critical)")
        log_verification(f"Summary: {summary}")

        if passed and confidence >= threshold:
            log_debug("AI verification passed!")
            log_verification("=== AI Verification PASSED ===\n")

            plan_state["verification"] = {
                "verified_at": datetime.now().isoformat(),
                "passed": True,
                "confidence": confidence,
                "summary": summary
            }
            save_plan_state(plan_state, plan_state_file)

            output_hook_response(
                True,
                f"✅ AI Verification passed ({confidence}% confidence)\n{summary}"
            )
        else:
            log_debug(f"AI verification failed: {len(critical_gaps)} critical gaps, {len(critical_mismatches)} critical mismatches")
            log_verification("=== AI Verification FAILED ===\n")

            plan_state = add_remediation_tasks(plan_state, result)
            save_plan_state(plan_state, plan_state_file)

            # Build failure message
            issues = []
            for gap in critical_gaps + warning_gaps:
                issues.append(f"  ⚠️ GAP: {gap.get('description', 'Unknown')[:80]}")
            for mismatch in critical_mismatches + warning_mismatches:
                expected = mismatch.get("expected", "")[:40]
                actual = mismatch.get("actual", "")[:40]
                issues.append(f"  ⚠️ MISMATCH: Expected '{expected}' but got '{actual}'")

            issues_str = "\n".join(issues[:5])
            if len(issues) > 5:
                issues_str += f"\n  ... and {len(issues) - 5} more issues"

            output_hook_response(
                False,
                f"❌ AI Verification FAILED ({confidence}% confidence)\n\n"
                f"{summary}\n\n"
                f"Issues found:\n{issues_str}\n\n"
                f"👉 Fix these issues before stopping."
            )

    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        output_hook_response(True)
    except Exception as e:
        log_debug(f"Unexpected error: {e}")
        output_hook_response(True, f"⚠️ AI verification skipped: {str(e)[:100]}")


if __name__ == "__main__":
    main()
