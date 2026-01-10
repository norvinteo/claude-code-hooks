#!/usr/bin/env python3
import json
import sys
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path

def send_tcp_notification(message, host='localhost', port=9999):
    try:
        windows_ip = os.environ.get('WINDOWS_NOTIFY_IP', host)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((windows_ip, port))
            notification_data = {
                'type': 'agent_complete',
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
            s.send(json.dumps(notification_data).encode() + b'\n')
            return True
    except Exception:
        return False

def write_notification_file(message):
    try:
        notify_path = Path("{{PROJECT_DIR}}/progress/notifications.txt")
        notify_path.parent.mkdir(parents=True, exist_ok=True)
        with open(notify_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
        sound_marker = Path("{{PROJECT_DIR}}/progress/PLAY_SOUND.txt")
        sound_marker.write_text(datetime.now().isoformat())
        return True
    except Exception:
        return False

def send_pushover_notification(message):
    try:
        token = os.environ.get('PUSHOVER_APP_TOKEN', '')
        user_key = os.environ.get('PUSHOVER_USER_KEY', '')
        if token and user_key:
            import urllib.request
            import urllib.parse
            data = urllib.parse.urlencode({
                'token': token,
                'user': user_key,
                'message': message,
                'title': 'Agent Complete',
                'sound': 'pushover',
                'priority': 0
            }).encode()
            req = urllib.request.Request('https://api.pushover.net/1/messages.json')
            response = urllib.request.urlopen(req, data, timeout=5)
            return response.status == 200
    except:
        pass
    return False

def send_slack_notification(message, title="Agent Complete"):
    try:
        webhook_url = os.environ.get('SLACK_WEBHOOK_URL', '')
        if not webhook_url:
            return False
        import urllib.request
        payload = {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"{title}", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
            ]
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 200
    except Exception:
        pass
    return False

def send_discord_notification(message, title="Agent Complete"):
    try:
        webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
        if not webhook_url:
            return False
        import urllib.request
        payload = {
            "embeds": [{
                "title": f"{title}",
                "description": message,
                "color": 5814783,
                "timestamp": datetime.now().isoformat(),
                "footer": {"text": "Claude Code Agent"}
            }]
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 204
    except Exception:
        pass
    return False

def send_telegram_notification(message, title="Agent Complete"):
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        if not bot_token or not chat_id:
            return False
        import urllib.request
        import urllib.parse
        text = f"*{title}*\n\n{message}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
        req = urllib.request.Request(url, data=data)
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 200
    except Exception:
        pass
    return False

def send_tmux_notification(message):
    try:
        if 'TMUX' in os.environ:
            subprocess.run(['tmux', 'display-message', '-d', '2000', f"{message}"], capture_output=True, timeout=2)
            subprocess.run(['tmux', 'set-option', '-g', 'status-right', f'"Agent Complete: {message}"'], capture_output=True, timeout=2)
            return True
    except:
        pass
    return False

def play_terminal_bell():
    try:
        sys.stderr.write('\a')
        sys.stderr.flush()
        subprocess.run(['tput', 'bel'], capture_output=True, timeout=1)
        return True
    except:
        return False

def log_completion(agent_name, session_id, task_info=None):
    try:
        log_path = Path("{{PROJECT_DIR}}/progress/agent_completions.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] Agent: {agent_name} | Session: {session_id}\n")
            if task_info:
                f.write(f"  Task: {task_info.get('task_id', 'N/A')} | Status: COMPLETED\n")
        json_log_path = Path("{{PROJECT_DIR}}/progress/completions.json")
        completion_entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "session_id": session_id,
            "task_info": task_info
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
    except Exception:
        return False

def send_mac_notification(message, title="Agent Complete"):
    try:
        if sys.platform == "darwin" or os.environ.get('NOTIFICATION_MODE') == 'local':
            sound = os.environ.get('NOTIFICATION_SOUND', 'Glass')
            applescript = f'''display notification "{message}" with title "{title}" sound name "{sound}"'''
            subprocess.run(['osascript', '-e', applescript], capture_output=True, timeout=2)
            try:
                subprocess.run(['terminal-notifier', '-title', title, '-message', message, '-sound', 'default'], capture_output=True, timeout=2)
            except FileNotFoundError:
                pass
            if os.environ.get('ENABLE_VOICE_NOTIFICATIONS') == 'true':
                subprocess.run(['say', message], capture_output=True, timeout=5)
            return True
    except Exception:
        pass
    return False

def main():
    try:
        data = json.load(sys.stdin)
        agent_name = data.get("agent_name", data.get("subagent_type", "Unknown"))
        session_id = data.get("session_id", "")
        stop_reason = data.get("stop_reason", "completed")
        if stop_reason not in ["completed", "finish"]:
            sys.exit(0)
        task_info = None
        if "task_id" in data or "task" in data:
            task_info = {"task_id": data.get("task_id", data.get("task", "")), "status": "COMPLETED"}
        message = f"Agent '{agent_name}' completed task"
        if task_info and task_info.get("task_id"):
            message = f"Agent '{agent_name}' completed {task_info['task_id']}"
        log_completion(agent_name, session_id, task_info)
        methods_tried = []
        if send_mac_notification(message):
            methods_tried.append("Mac")
        if os.environ.get('WINDOWS_NOTIFY_IP') and send_tcp_notification(message):
            methods_tried.append("TCP")
        if write_notification_file(message):
            methods_tried.append("File")
        if send_pushover_notification(message):
            methods_tried.append("Pushover")
        if send_slack_notification(message):
            methods_tried.append("Slack")
        if send_discord_notification(message):
            methods_tried.append("Discord")
        if send_telegram_notification(message):
            methods_tried.append("Telegram")
        if send_tmux_notification(message):
            methods_tried.append("tmux")
        if play_terminal_bell():
            methods_tried.append("Bell")
        if methods_tried:
            debug_log = Path("{{PROJECT_DIR}}/progress/.notification_debug.log")
            with open(debug_log, "a") as f:
                f.write(f"{datetime.now().isoformat()} - Sent via: {', '.join(methods_tried)}\n")
    except json.JSONDecodeError:
        pass
    except Exception as e:
        error_log = Path("{{PROJECT_DIR}}/progress/.notification_errors.log")
        with open(error_log, "a") as f:
            f.write(f"{datetime.now().isoformat()} - Error: {str(e)}\n")

if __name__ == "__main__":
    main()
