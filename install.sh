#!/bin/bash
#
# Claude Code Hooks Installer
# ============================
# Installs the Ralph-style autonomous hooks system to any project.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main/install.sh | bash -s /path/to/project
#
# Or:
#   ./install.sh /path/to/your/project
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# GitHub repository
GITHUB_RAW="https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main"

# Target project
TARGET_PROJECT="${1:-$(pwd)}"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}           Claude Code Hooks Installer                          ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Validate target
if [ ! -d "$TARGET_PROJECT" ]; then
    echo -e "${YELLOW}Creating target directory: $TARGET_PROJECT${NC}"
    mkdir -p "$TARGET_PROJECT"
fi

TARGET_PROJECT="$(cd "$TARGET_PROJECT" && pwd)"
TARGET_HOOKS="$TARGET_PROJECT/.claude/hooks"
TARGET_SETTINGS="$TARGET_PROJECT/.claude/settings.json"

echo -e "${YELLOW}Target:${NC} $TARGET_PROJECT"
echo ""

# Create target directories
echo -e "${GREEN}Creating directories...${NC}"
mkdir -p "$TARGET_HOOKS"
mkdir -p "$TARGET_HOOKS/archive"
mkdir -p "$TARGET_HOOKS/sessions"
mkdir -p "$TARGET_PROJECT/.claude/plans"
mkdir -p "$TARGET_PROJECT/.claude/continuations"
mkdir -p "$TARGET_PROJECT/progress"
mkdir -p "$TARGET_PROJECT/progress/daily"

# List of hook files to download
HOOK_FILES=(
    "plan_initializer.py"
    "plan_tracker.py"
    "plan_session_helper.py"
    "todo_sync.py"
    "inject_plan_context.py"
    "stop_verifier.py"
    "completion_validator.py"
    "session_cleanup.py"
    "continuation_enforcer.py"
    "cost_tracker.py"
    "task_monitor.py"
    "agent_complete_notify.py"
    "dashboard.py"
    "auto_continue.sh"
)

# Download hook files
echo -e "${GREEN}Downloading hook files...${NC}"
for file in "${HOOK_FILES[@]}"; do
    if curl -sfL "$GITHUB_RAW/hooks/$file" -o "$TARGET_HOOKS/$file"; then
        chmod +x "$TARGET_HOOKS/$file"
        echo "  ✓ $file"
    else
        echo -e "  ${YELLOW}⚠ $file not found, skipping${NC}"
    fi
done

# Create config.json
echo -e "${GREEN}Creating config.json...${NC}"
cat > "$TARGET_HOOKS/config.json" << 'EOF'
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
      "command": "npm run tsc --noEmit || bun run tsc --noEmit || yarn tsc --noEmit",
      "timeout": 120,
      "required": true
    },
    {
      "name": "Lint",
      "command": "npm run lint || bun run lint || yarn lint",
      "timeout": 60,
      "required": false
    },
    {
      "name": "Build",
      "command": "npm run build || bun run build || yarn build",
      "timeout": 300,
      "required": true
    }
  ]
}
EOF
echo "  ✓ config.json"

# Create empty plan_state.json
echo -e "${GREEN}Creating plan_state.json...${NC}"
cat > "$TARGET_HOOKS/plan_state.json" << 'EOF'
{
  "session_id": null,
  "plan_source": null,
  "plan_file": null,
  "name": null,
  "items": [],
  "created_at": null,
  "updated_at": null
}
EOF
echo "  ✓ plan_state.json"

# Create settings.json
echo -e "${GREEN}Creating settings.json...${NC}"
cat > "$TARGET_SETTINGS" << EOF
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/plan_initializer.py"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/continuation_enforcer.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Task",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/inject_plan_context.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "TodoWrite",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/todo_sync.py"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/plan_tracker.py"
          }
        ]
      },
      {
        "matcher": "Task",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/task_monitor.py"
          }
        ]
      },
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/cost_tracker.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/stop_verifier.py"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/completion_validator.py"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/session_cleanup.py"
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $TARGET_HOOKS/agent_complete_notify.py"
          }
        ]
      }
    ]
  }
}
EOF
echo "  ✓ settings.json"

# Verify installation
echo ""
echo -e "${GREEN}Verifying installation...${NC}"
ERRORS=0
for file in "${HOOK_FILES[@]}"; do
    if [[ "$file" == *.py ]]; then
        if [ -f "$TARGET_HOOKS/$file" ]; then
            if python3 -m py_compile "$TARGET_HOOKS/$file" 2>/dev/null; then
                echo "  ✓ $file"
            else
                echo -e "  ${RED}✗ $file (syntax error)${NC}"
                ERRORS=$((ERRORS + 1))
            fi
        fi
    elif [[ "$file" == *.sh ]]; then
        if [ -f "$TARGET_HOOKS/$file" ]; then
            echo "  ✓ $file"
        fi
    fi
done

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}Installation complete! ✅${NC}"
else
    echo -e "${YELLOW}Installation complete with $ERRORS errors${NC}"
fi
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Files installed to: $TARGET_HOOKS"
echo ""
echo "Usage:"
echo "  /plan <task name>     - Start a new plan"
echo "  /showplan             - Show current plan status"
echo "  /clearplan            - Clear the plan"
echo "  /continue             - List available continuations"
echo "  /continue <id>        - Continue from a previous session"
echo ""
echo "Configuration: $TARGET_HOOKS/config.json"
echo ""
echo -e "${YELLOW}Autonomous Operation (optional):${NC}"
echo "  1. Start Claude in tmux: tmux new -s claude"
echo "  2. In another terminal: $TARGET_HOOKS/auto_continue.sh claude"
echo ""
echo -e "${YELLOW}Session Dashboard (optional):${NC}"
echo "  python3 $TARGET_HOOKS/dashboard.py"
echo "  Opens: http://localhost:8765"
echo ""
echo -e "${YELLOW}Optional: Set environment variables for notifications:${NC}"
echo "  export SLACK_WEBHOOK_URL='https://hooks.slack.com/...'"
echo "  export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'"
echo "  export TELEGRAM_BOT_TOKEN='...' TELEGRAM_CHAT_ID='...'"
echo ""
