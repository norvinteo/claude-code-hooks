#!/usr/bin/env python3
import json
import sys
import os
from datetime import datetime
from pathlib import Path

def check_task_completion(data):
    try:
        tool_name = data.get("tool_name", "")
        
        if tool_name == "Task":
            result = data.get("result", {})
            if isinstance(result, str) and "completed" in result.lower():
                return True
            
            if isinstance(result, dict):
                status = result.get("status", "")
                if status.lower() in ["completed", "done", "finished"]:
                    return True
        
        if tool_name in ["Write", "Edit", "MultiEdit"]:
            file_path = data.get("file_path", "")
            if "/progress/tasks/" in file_path and "TASK-" in file_path:
                content = data.get("content", data.get("new_string", ""))
                if "Status: COMPLETED" in content or "status: completed" in content.lower():
                    import re
                    match = re.search(r'TASK-\d+', file_path)
                    if match:
                        return match.group(0)
        
        return None
    except:
        return None

def send_notification(task_id, message="Task completed"):
    try:
        import socket
        
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
        
        notify_path = Path("{{PROJECT_DIR}}/progress/task_notifications.txt")
        notify_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(notify_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Task {task_id} completed\n")
        
        sys.stderr.write('\a')
        sys.stderr.flush()
        
        return True
    except:
        return False

def log_task_completion(task_id):
    try:
        log_path = Path("{{PROJECT_DIR}}/progress/task_completions.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] Task completed: {task_id}\n")
        
        json_log_path = Path("{{PROJECT_DIR}}/progress/task_completions.json")
        
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
        data = json.load(sys.stdin)
        
        task_result = check_task_completion(data)
        
        if task_result:
            if isinstance(task_result, str) and task_result.startswith("TASK-"):
                task_id = task_result
            else:
                task_id = data.get("task_id", "TASK-UNKNOWN")
            
            log_task_completion(task_id)
            send_notification(task_id)
        
    except json.JSONDecodeError:
        pass
    except Exception as e:
        error_log = Path("{{PROJECT_DIR}}/progress/.task_monitor_errors.log")
        with open(error_log, "a") as f:
            f.write(f"{datetime.now().isoformat()} - Error: {str(e)}\n")

if __name__ == "__main__":
    main()
