# Claude Code Hooks

Ralph-style autonomous development hooks for Claude Code with stop blocking, code validation, and notifications.

## Features

- **Plan Commands** - `/plan`, `/showplan`, `/clearplan`
- **Auto-sync** - TodoWrite completions sync to plan
- **Stop Blocking** - Prevents stopping until all tasks complete
- **Loop Prevention** - Allows stop after 5 blocked attempts
- **Code Validation** - Runs TypeScript, lint, and build checks
- **Session Archiving** - Archives completed plans
- **Cost Tracking** - Tracks API usage per session
- **Multi-channel Notifications** - Mac, Slack, Discord, Telegram

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
/plan Fix the login page bug    # Start a new plan
/showplan                        # Show current plan status
/clearplan                       # Clear the plan
```

Claude will:
- Track tasks via TodoWrite
- Show progress before tool use
- Block stopping until complete
- Run validation on completion

## How It Works

### Stop Blocking

When you create a plan, Claude Code cannot stop until all tasks are completed:

1. User types `/plan Fix authentication bug`
2. Claude creates plan items via TodoWrite
3. When Claude tries to stop, `stop_verifier.py` checks for incomplete items
4. If incomplete → Block stop and prompt continuation
5. If all complete → Allow stop and run validation

### Loop Prevention

To prevent infinite loops, stop is allowed after 5 blocked attempts.

### Code Validation

When all plan items are complete, the system runs:
- TypeScript type checking
- ESLint linting
- Build verification

If validation fails, new fix tasks are added to the plan.

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
  "notifications": {
    "mac": true,
    "slack": false,
    "discord": false,
    "telegram": false
  }
}
```

## Notifications

Set environment variables for notifications:

```bash
# Slack
export SLACK_WEBHOOK_URL='https://hooks.slack.com/...'

# Discord
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'

# Telegram
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'
```

## Hook Events

| Hook | Event | Purpose |
|------|-------|--------|
| `plan_initializer.py` | PrePromptSubmit | Handle /plan commands |
| `continuation_enforcer.py` | PrePromptSubmit | Reinforce continuation |
| `inject_plan_context.py` | PreToolUse | Show plan progress |
| `todo_sync.py` | PostToolUse (TodoWrite) | Sync todos to plan |
| `plan_tracker.py` | PostToolUse (Write/Edit) | Parse plan files |
| `task_monitor.py` | PostToolUse (Task) | Log task completion |
| `cost_tracker.py` | PostToolUse | Track API costs |
| `stop_verifier.py` | Stop | Block until complete |
| `completion_validator.py` | Stop | Run code checks |
| `session_cleanup.py` | Stop | Archive and cleanup |
| `agent_complete_notify.py` | SubagentStop | Send notifications |

## Credits

Inspired by the Ralph Wiggum technique for autonomous Claude Code development.

## License

MIT License - see [LICENSE](LICENSE)
