#!/usr/bin/env python3
import json
import sys
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path

def send_tcp_notification(message, host='localhost', port=9999):
    """Send notification via TCP socket to Windows listener"""
    try:
        # Try to get Windows IP from environment or use default
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
    except Exception as e:
        # Log connection failure silently
        return False

def write_notification_file(message):
    """Write to a shared file that Windows can monitor"""
    try:
        notify_path = HOOKS_DIR.parent / "progress/notifications.txt"
        notify_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(notify_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
        
        # Also create a trigger file for sound
        sound_marker = HOOKS_DIR.parent / "progress/PLAY_SOUND.txt"
        sound_marker.write_text(datetime.now().isoformat())
        return True
    except Exception:
        return False

def send_pushover_notification(message):
    """Send notification via Pushover API (works everywhere)"""
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
    """Send notification via Slack webhook.

    Set SLACK_WEBHOOK_URL environment variable to enable.
    Get webhook URL from: Slack App > Incoming Webhooks
    """
    try:
        webhook_url = os.environ.get('SLACK_WEBHOOK_URL', '')
        if not webhook_url:
            return False

        import urllib.request

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🤖 {title}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 200
    except Exception:
        pass
    return False


def send_discord_notification(message, title="Agent Complete"):
    """Send notification via Discord webhook.

    Set DISCORD_WEBHOOK_URL environment variable to enable.
    Get webhook URL from: Server Settings > Integrations > Webhooks
    """
    try:
        webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
        if not webhook_url:
            return False

        import urllib.request

        payload = {
            "embeds": [
                {
                    "title": f"🤖 {title}",
                    "description": message,
                    "color": 5814783,  # Blue color
                    "timestamp": datetime.now().isoformat(),
                    "footer": {
                        "text": "Claude Code Agent"
                    }
                }
            ]
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 204  # Discord returns 204 on success
    except Exception:
        pass
    return False


def send_telegram_notification(message, title="Agent Complete"):
    """Send notification via Telegram bot.

    Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables to enable.
    Get bot token from @BotFather, chat ID from @userinfobot
    """
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')

        if not bot_token or not chat_id:
            return False

        import urllib.request
        import urllib.parse

        text = f"🤖 *{title}*\n\n{message}"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }).encode()

        req = urllib.request.Request(url, data=data)
        response = urllib.request.urlopen(req, timeout=5)
        return response.status == 200
    except Exception:
        pass
    return False

def send_tmux_notification(message):
    """Send notification to tmux if running in tmux session"""
    try:
        if 'TMUX' in os.environ:
            # Display message in tmux
            subprocess.run(
                ['tmux', 'display-message', '-d', '2000', f"📢 {message}"],
                capture_output=True,
                timeout=2
            )
            
            # Also set status bar alert
            subprocess.run(
                ['tmux', 'set-option', '-g', 'status-right', f'"Agent Complete: {message}"'],
                capture_output=True,
                timeout=2
            )
            return True
    except:
        pass
    return False

def play_terminal_bell():
    """Play terminal bell sound (works over SSH)"""
    try:
        # Send bell character to stderr
        sys.stderr.write('\a')
        sys.stderr.flush()
        
        # Also try tput if available
        subprocess.run(['tput', 'bel'], capture_output=True, timeout=1)
        return True
    except:
        return False

def log_completion(agent_name, session_id, task_info=None):
    """Log the completion to progress files"""
    try:
        log_path = HOOKS_DIR.parent / "progress/agent_completions.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Write to main log
        with open(log_path, "a") as f:
            f.write(f"[{timestamp}] Agent: {agent_name} | Session: {session_id}\n")
            if task_info:
                f.write(f"  Task: {task_info.get('task_id', 'N/A')} | Status: COMPLETED\n")
        
        # Write to JSON log for structured data
        json_log_path = HOOKS_DIR.parent / "progress/completions.json"
        
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
    """Send native Mac notification"""
    try:
        # Check if we're on Mac and in local mode
        if sys.platform == "darwin" or os.environ.get('NOTIFICATION_MODE') == 'local':
            # Method 1: osascript (always available on Mac)
            sound = os.environ.get('NOTIFICATION_SOUND', 'Glass')
            applescript = f'''display notification "{message}" with title "{title}" sound name "{sound}"'''
            subprocess.run(['osascript', '-e', applescript], capture_output=True, timeout=2)
            
            # Method 2: terminal-notifier (if installed via homebrew)
            try:
                subprocess.run(
                    ['terminal-notifier', '-title', title, '-message', message, '-sound', 'default'],
                    capture_output=True,
                    timeout=2
                )
            except FileNotFoundError:
                pass  # terminal-notifier not installed
            
            # Method 3: Voice notification (if enabled)
            if os.environ.get('ENABLE_VOICE_NOTIFICATIONS') == 'true':
                subprocess.run(['say', message], capture_output=True, timeout=5)
            
            return True
    except Exception:
        pass
    return False

def main():
    try:
        # Read JSON input from stdin
        data = json.load(sys.stdin)
        
        # Extract information with defaults
        agent_name = data.get("agent_name", data.get("subagent_type", "Unknown"))
        session_id = data.get("session_id", "")
        stop_reason = data.get("stop_reason", "completed")
        
        # Check if this is actually a completion (not an error or cancel)
        if stop_reason not in ["completed", "finish"]:
            sys.exit(0)  # Exit silently if not a successful completion
        
        # Extract task information if available
        task_info = None
        if "task_id" in data or "task" in data:
            task_info = {
                "task_id": data.get("task_id", data.get("task", "")),
                "status": "COMPLETED"
            }
        
        # Prepare notification message
        message = f"Agent '{agent_name}' completed task"
        if task_info and task_info.get("task_id"):
            message = f"Agent '{agent_name}' completed {task_info['task_id']}"
        
        # Log the completion
        log_completion(agent_name, session_id, task_info)
        
        # Send notifications through multiple channels
        # Track which methods succeeded
        methods_tried = []
        
        # Method 1: Mac native notification (for local work)
        if send_mac_notification(message):
            methods_tried.append("Mac")
        
        # Method 2: TCP socket to Windows listener (for remote work)
        if os.environ.get('WINDOWS_NOTIFY_IP') and send_tcp_notification(message):
            methods_tried.append("TCP")
        
        # Method 3: Write to monitored file
        if write_notification_file(message):
            methods_tried.append("File")
        
        # Method 4: Pushover (if configured)
        if send_pushover_notification(message):
            methods_tried.append("Pushover")

        # Method 5: Slack (if configured)
        if send_slack_notification(message):
            methods_tried.append("Slack")

        # Method 6: Discord (if configured)
        if send_discord_notification(message):
            methods_tried.append("Discord")

        # Method 7: Telegram (if configured)
        if send_telegram_notification(message):
            methods_tried.append("Telegram")

        # Method 8: tmux notification (if in tmux)
        if send_tmux_notification(message):
            methods_tried.append("tmux")

        # Method 9: Terminal bell (always try this)
        if play_terminal_bell():
            methods_tried.append("Bell")
        
        # Log which notification methods were used
        if methods_tried:
            debug_log = HOOKS_DIR.parent / "progress/.notification_debug.log"
            with open(debug_log, "a") as f:
                f.write(f"{datetime.now().isoformat()} - Sent via: {', '.join(methods_tried)}\n")
        
    except json.JSONDecodeError:
        # Not valid JSON, exit silently
        pass
    except Exception as e:
        # Log any errors for debugging
        error_log = HOOKS_DIR.parent / "progress/.notification_errors.log"
        with open(error_log, "a") as f:
            f.write(f"{datetime.now().isoformat()} - Error: {str(e)}\n")

if __name__ == "__main__":
    main()