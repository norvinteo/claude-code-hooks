# Claude Code Hooks

Ralph-style autonomous development hooks for Claude Code with stop blocking, code validation, and notifications.

## Features

- **Plan Commands** - `@plan`, `@showplan`, `@clearplan`
- **Multi-Session Continuation** - `@continue` to resume incomplete sessions
- **Session Dashboard** - Web UI to monitor all sessions at `http://localhost:8765`
- **Auto-sync** - TodoWrite completions sync to plan (smart keyword matching)
- **Stop Blocking** - Prevents stopping until all tasks complete
- **Loop Prevention** - Allows stop after configurable blocked attempts (default: 5)
- **Force Stop** - Say "force stop" or `@force-stop` to bypass blocking
- **Autonomous Operation** - Auto-continue script for tmux sessions
- **Code Validation** - Runs TypeScript, lint, and build checks
- **Session Archiving** - Archives completed plans with daily progress logs
- **Cost Tracking** - Tracks API usage per session
- **Multi-channel Notifications** - Mac, Slack, Discord, Telegram, and more

## Quick Install

### One-liner (Recommended)

```bash
curl -sL https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main/install.sh | bash -s /path/to/your/project
```

Or install to current directory:

```bash
curl -sL https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main/install.sh | bash -s .
```

### Clone and Install

```bash
git clone https://github.com/norvinteo/claude-code-hooks.git
./claude-code-hooks/install.sh /path/to/your/project
```

## Usage

After installation, use these commands in Claude Code:

```
@plan Fix the login page bug    # Start a new plan
@showplan                        # Show current plan status
@clearplan                       # Clear the plan
@continue                        # List available continuations
@continue abc12345               # Continue from session starting with abc12345
```

**Note:** Commands use `@` prefix to avoid conflicts with Claude Code's skill system (`/`) and bash history (`!`).

Claude will:
- Track tasks via TodoWrite
- Show progress before tool use
- Block stopping until complete
- Run validation on completion

## How It Works

### Stop Blocking

When you create a plan, Claude Code cannot stop until all tasks are completed:

1. User types `@plan Fix authentication bug`
2. Claude creates plan items via TodoWrite
3. When Claude tries to stop, `stop_verifier.py` checks for incomplete items
4. If incomplete → Block stop and prompt continuation
5. If all complete → Allow stop and run validation

### Smart Todo Matching

The `todo_sync.py` hook uses intelligent matching to sync TodoWrite completions to plan items:

- **Exact match first** - No processing needed for identical text
- **Keyword extraction** - Filters stop words, extracts meaningful terms
- **Word stemming** - `implemented` → `implement`, `verified` → `verify`
- **Synonym expansion** - `create` ↔ `add`, `build`, `implement`, `write`
- **Jaccard similarity** - Scores overlap between keyword sets

Example: "Login page implemented" matches "Create the login page"

### Loop Prevention

To prevent infinite loops, stop is allowed after a configurable number of blocked attempts (default: 5). You can change this in `config.json`:

```json
{
  "max_stop_attempts": 10
}
```

### Force Stop

Say any of these to bypass stop blocking:
- `@force-stop`
- `force stop`
- `stop anyway`
- `ignore incomplete`
- `skip verification`

### Code Validation

When all plan items are complete, the system runs:
- TypeScript type checking
- ESLint linting
- Build verification

If validation fails, new fix tasks are added to the plan.

---

## Multi-Session Continuation

When a session ends with incomplete tasks, the state is automatically saved. New sessions can continue from where the previous session left off.

### How It Works

1. Session ends with incomplete tasks (or force stop)
2. `session_cleanup.py` saves the continuation state to `.claude/continuations/`
3. New session uses `@continue` to list available continuations
4. `@continue <id>` loads the previous session's tasks

### Commands

```
@continue           # List all available continuations
@continuations      # Alias for @continue
@continue abc12345  # Continue from session starting with abc12345
```

### Example Output

```
## Available Session Continuations

Previous sessions with incomplete tasks:

**1. Fix authentication bug**
   Progress: 3/5 (2 remaining)
   Session: `abc12345...` | Saved: 2024-01-20T15:30

---
To continue a session: `@continue {session_id_prefix}`
Example: `@continue abc12345`
```

### Auto-Cleanup

Continuation files older than 7 days are automatically removed during session cleanup.

---

## Session Dashboard

A web-based dashboard to monitor and manage all Claude sessions.

### Starting the Dashboard

```bash
python3 .claude/hooks/dashboard.py
```

Opens: `http://localhost:8765`

### Features

- **Session Overview** - View all active plan sessions with progress
- **Cost Tracking** - See accumulated costs per session
- **Task Progress** - Visual progress bars and task lists
- **Session Management** - Clear individual sessions or all at once
- **Auto-Refresh** - Updates every 5 seconds (toggleable)

### Dashboard Stats

- Total plan sessions
- Completed tasks count
- Total API cost
- Total tokens used

---

## Autonomous Operation (tmux)

For fully autonomous operation without manual intervention, use the `auto_continue.sh` script:

### Setup

1. **Start Claude Code in a tmux session:**
   ```bash
   tmux new -s claude
   claude  # Start Claude Code
   ```

2. **In another terminal, run the auto-continue script:**
   ```bash
   .claude/hooks/auto_continue.sh claude
   ```

### How It Works

The script monitors your tmux session for "STOP BLOCKED" messages and automatically sends "c" to continue:

```
🤖 Auto-continue monitoring started for tmux session: claude
   Press Ctrl+C to stop
18:30:45 🔄 Stop blocked detected - sending 'c' to continue...
18:32:12 🔄 Stop blocked detected - sending 'c' to continue...
```

### Features

- **Duplicate detection** - Won't send multiple "c" commands for the same block
- **Session monitoring** - Waits if tmux session isn't found
- **Clean exit** - Press Ctrl+C to stop monitoring

---

## Configuration

Edit `.claude/hooks/config.json`:

```json
{
  "plan_verification": true,
  "auto_code_review": true,
  "cost_tracking": true,
  "max_session_cost": 10.00,
  "cost_warning_threshold": 0.8,
  "max_stop_attempts": 5,
  "archive_old_plans": true,
  "notifications": {
    "mac": true,
    "terminal_bell": true,
    "slack": false,
    "discord": false,
    "telegram": false,
    "pushover": false
  },
  "validation_commands": [
    {
      "name": "TypeScript Check",
      "command": "npm run tsc --noEmit",
      "timeout": 120,
      "required": true
    },
    {
      "name": "Lint",
      "command": "npm run lint",
      "timeout": 60,
      "required": false
    },
    {
      "name": "Build",
      "command": "npm run build",
      "timeout": 300,
      "required": true
    }
  ]
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `plan_verification` | boolean | `true` | Enable plan tracking and stop blocking |
| `auto_code_review` | boolean | `true` | Auto-trigger code review on completion |
| `cost_tracking` | boolean | `true` | Track API usage costs |
| `max_session_cost` | number | `10.00` | Maximum session cost in USD |
| `cost_warning_threshold` | number | `0.8` | Warn at this percentage of max cost |
| `max_stop_attempts` | number | `5` | Allow stop after N blocked attempts |
| `archive_old_plans` | boolean | `true` | Archive completed plans |
| `notifications` | object | - | Enable/disable notification channels |
| `validation_commands` | array | - | Commands to run on completion |

---

## Notifications

The notification system alerts you when Claude agents complete tasks. Supports multiple channels simultaneously.

### Supported Notification Methods

| Method | Platform | Requirements |
|--------|----------|--------------|
| **Mac Notification** | macOS | Built-in (automatic) |
| **Terminal Bell** | All | Built-in (automatic) |
| **File Log** | All | Built-in (automatic) |
| **Slack** | All | Webhook URL |
| **Discord** | All | Webhook URL |
| **Telegram** | All | Bot Token + Chat ID |
| **Pushover** | All | App Token + User Key |
| **tmux** | Linux/macOS | tmux session |
| **TCP Socket** | All | Custom listener |

### Quick Setup

Add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Pick the ones you want to use:
export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/YOUR_WEBHOOK_URL'
export TELEGRAM_BOT_TOKEN='your_bot_token_here'
export TELEGRAM_CHAT_ID='your_chat_id_here'
```

---

### Slack Setup

1. **Create a Slack App**
   - Go to [api.slack.com/apps](https://api.slack.com/apps)
   - Click "Create New App" → "From scratch"
   - Name it (e.g., "Claude Notifications") and select your workspace

2. **Enable Incoming Webhooks**
   - In your app settings, go to "Incoming Webhooks"
   - Toggle "Activate Incoming Webhooks" to ON
   - Click "Add New Webhook to Workspace"
   - Select the channel for notifications
   - Copy the webhook URL

3. **Set Environment Variable**
   ```bash
   export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXXXX'
   ```

4. **Test It**
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"text":"Test notification from Claude hooks!"}' \
     "$SLACK_WEBHOOK_URL"
   ```

---

### Discord Setup

1. **Create a Webhook**
   - Open Discord and go to your server
   - Right-click the channel → "Edit Channel"
   - Go to "Integrations" → "Webhooks"
   - Click "New Webhook"
   - Name it (e.g., "Claude Bot")
   - Copy the webhook URL

2. **Set Environment Variable**
   ```bash
   export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/XXXXXXXXXX/YYYYYYYYYY'
   ```

3. **Test It**
   ```bash
   curl -X POST -H 'Content-type: application/json' \
     --data '{"content":"Test notification from Claude hooks!"}' \
     "$DISCORD_WEBHOOK_URL"
   ```

---

### Telegram Setup

1. **Create a Bot**
   - Open Telegram and search for `@BotFather`
   - Send `/newbot` and follow the prompts
   - Save the bot token you receive

2. **Get Your Chat ID**
   - Start a chat with your new bot (send any message)
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find `"chat":{"id":123456789}` in the response
   - That number is your chat ID

3. **Set Environment Variables**
   ```bash
   export TELEGRAM_BOT_TOKEN='your_bot_token_here'
   export TELEGRAM_CHAT_ID='your_chat_id_here'
   ```

4. **Test It**
   ```bash
   curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
     -d "chat_id=$TELEGRAM_CHAT_ID" \
     -d "text=Test notification from Claude hooks!"
   ```

---

### Pushover Setup

1. **Create Account & App**
   - Sign up at [pushover.net](https://pushover.net)
   - Note your User Key from the dashboard
   - Create an Application and note the API Token

2. **Set Environment Variables**
   ```bash
   export PUSHOVER_USER_KEY='your_user_key_here'
   export PUSHOVER_APP_TOKEN='your_app_token_here'
   ```

3. **Test It**
   ```bash
   curl -s -F "token=$PUSHOVER_APP_TOKEN" \
     -F "user=$PUSHOVER_USER_KEY" \
     -F "message=Test notification from Claude hooks!" \
     https://api.pushover.net/1/messages.json
   ```

---

### Mac Notifications (Built-in)

Mac notifications work automatically on macOS. Optional customizations:

```bash
# Custom notification sound (default: Glass)
export NOTIFICATION_SOUND='Ping'

# Enable voice announcements
export ENABLE_VOICE_NOTIFICATIONS='true'
```

**Available sounds:** Basso, Blow, Bottle, Frog, Funk, Glass, Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine, Tink

**Optional: Install terminal-notifier for enhanced notifications:**
```bash
brew install terminal-notifier
```

---

### TCP Socket Notifications

For custom notification systems (e.g., Windows machine, home automation):

```bash
# IP of the machine running the notification listener
export WINDOWS_NOTIFY_IP='192.168.1.100'
```

The hook sends JSON to port 9999:
```json
{
  "type": "agent_complete",
  "message": "Agent 'frontend-developer' completed Build login page",
  "timestamp": "2024-01-10T16:25:38.738263"
}
```

---

### Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL | `https://hooks.slack.com/...` |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | `https://discord.com/api/webhooks/...` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token | Your bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID | Your chat ID |
| `PUSHOVER_USER_KEY` | Pushover user key | Your user key |
| `PUSHOVER_APP_TOKEN` | Pushover application token | Your app token |
| `WINDOWS_NOTIFY_IP` | IP for TCP notifications | `192.168.1.100` |
| `NOTIFICATION_SOUND` | macOS sound name | `Glass`, `Ping`, etc. |
| `ENABLE_VOICE_NOTIFICATIONS` | Speak notifications aloud | `true` or `false` |
| `NOTIFICATION_MODE` | Force local notifications | `local` |

---

### Notification Files

The hook also writes to files for external monitoring:

| File | Purpose |
|------|---------|
| `progress/notifications.txt` | Human-readable notification log |
| `progress/agent_completions.log` | Detailed completion log |
| `progress/completions.json` | JSON log for parsing/automation |
| `progress/PLAY_SOUND.txt` | Marker file (for external sound triggers) |

---

### Testing Notifications

Test your notification setup:

```bash
# Simulate an agent completion
echo '{"agent_name":"test-agent","session_id":"test","stop_reason":"completed","task":"Test notification"}' | \
  python3 .claude/hooks/agent_complete_notify.py

# Check if it worked
cat progress/notifications.txt
cat progress/.notification_debug.log
```

---

### Troubleshooting

**Notifications not appearing?**
1. Check environment variables are exported: `echo $SLACK_WEBHOOK_URL`
2. Check the debug log: `cat progress/.notification_debug.log`
3. Check for errors: `cat progress/.notification_errors.log`

**Slack webhook returns error?**
- Verify the webhook URL is correct
- Check if the Slack app is still installed in the workspace
- Try regenerating the webhook

**Telegram not working?**
- Make sure you've started a chat with the bot first
- Verify the chat ID is correct (should be a number)
- For group chats, the chat ID is negative

**Mac notifications not showing?**
- Check System Preferences → Notifications → Terminal (or your terminal app)
- Ensure notifications are enabled for the app

---

## Hook Events

| Hook | Event | Purpose |
|------|-------|--------|
| `plan_initializer.py` | UserPromptSubmit | Handle @plan, @continue commands |
| `continuation_enforcer.py` | UserPromptSubmit | Reinforce continuation |
| `inject_plan_context.py` | PreToolUse | Show plan progress |
| `todo_sync.py` | PostToolUse (TodoWrite) | Sync todos to plan |
| `plan_tracker.py` | PostToolUse (Write/Edit) | Parse plan files |
| `task_monitor.py` | PostToolUse (Task) | Log task completion |
| `cost_tracker.py` | PostToolUse | Track API costs |
| `stop_verifier.py` | Stop | Block until complete |
| `completion_validator.py` | Stop | Run code checks |
| `session_cleanup.py` | Stop | Archive, save continuations, cleanup |
| `agent_complete_notify.py` | SubagentStop | Send notifications |
| `plan_session_helper.py` | Module | Shared utilities for session tracking |
| `dashboard.py` | Standalone | Web dashboard for session monitoring |
| `auto_continue.sh` | External | Auto-continue in tmux |

## Credits

Inspired by the Ralph Wiggum technique for autonomous Claude Code development.

## License

MIT License - see [LICENSE](LICENSE)
