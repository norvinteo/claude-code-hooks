#!/usr/bin/env python3
import json
import sys
import os
from datetime import datetime
from pathlib import Path

def check_task_completion(data):
    """Check if a task was marked as completed"""
    try:
        # Look for task completion patterns
        tool_name = data.get("tool_name", "")
        
        if tool_name == "Task":
            # Check if task result indicates completion
            result = data.get("result", {})
            if isinstance(result, str) and "completed" in result.lower():
                return True
            
            # Check for task status updates
            if isinstance(result, dict):
                status = result.get("status", "")
                if status.lower() in ["completed", "done", "finished"]:
                    return True
        
        # Check for Write/Edit operations that update task files
        if tool_name in ["Write", "Edit", "MultiEdit"]:
            file_path = data.get("file_path", "")
            if "/progress/tasks/" in file_path and "TASK-" in file_path:
                # Check if content contains COMPLETED status
                content = data.get("content", data.get("new_string", ""))
                if "Status: COMPLETED" in content or "status: completed" in content.lower():
                    # Extract task ID from file path
                    import re
                    match = re.search(r'TASK-\d+', file_path)
                    if match:
                        return match.group(0)
        
        return None
    except:
        return None

def send_notification(task_id, message="Task completed"):
    """Send task completion notification"""
    try:
        # Import the notification functions from agent_complete_notify
        import socket
        
        # Send TCP notification to Windows
        windows_ip = os.environ.get('WINDOWS_NOTIFY_IP', 'localhost')
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect((windows_ip, 9999))
                notification_data = {
                    'type': 'task_complete',
                    'message': f"Task {task_id} completed",
                    'task_id': task_id,
                    'timestamp': datetime.now().isoformat()
                }
                s.send(json.dumps(notification_data).encode() + b'\n')
        except:
            pass
        
        # Write to notification file
        notify_path = HOOKS_DIR.parent / "progress/task_notifications.txt"
        notify_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(notify_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Task {task_id} completed\n")
        
        # Play terminal bell
        sys.stderr.write('\a')
        sys.stderr.flush()
        
        return True
    except:
        return False

def log_task_completion(task_id):
    """Log task completion to progress files"""
    try:
        log_path = HOOKS_DIR.parent / "progress/task_completions.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] Task completed: {task_id}\n")
        
        # Update JSON log
        json_log_path = HOOKS_DIR.parent / "progress/task_completions.json"
        
        completion_entry = {
            "timestamp": datetime.now().isoformat(),
            "task_id": task_id,
            "status": "COMPLETED"
        }
        
        if json_log_path.exists():
            with open(json_log_path, "r") as f:
                logs = json.load(f)
        else:
            logs = []
        
        logs.append(completion_entry)
        
        with open(json_log_path, "w") as f:
            json.dump(logs, f, indent=2)
        
        return True
    except:
        return False

def main():
    try:
        # Read JSON input from stdin
        data = json.load(sys.stdin)
        
        # Check if this is a task completion
        task_result = check_task_completion(data)
        
        if task_result:
            # Extract task ID
            if isinstance(task_result, str) and task_result.startswith("TASK-"):
                task_id = task_result
            else:
                task_id = data.get("task_id", "TASK-UNKNOWN")
            
            # Log the completion
            log_task_completion(task_id)
            
            # Send notification
            send_notification(task_id)
        
    except json.JSONDecodeError:
        # Not valid JSON, exit silently
        pass
    except Exception as e:
        # Log errors for debugging
        error_log = HOOKS_DIR.parent / "progress/.task_monitor_errors.log"
        with open(error_log, "a") as f:
            f.write(f"{datetime.now().isoformat()} - Error: {str(e)}\n")

if __name__ == "__main__":
    main()