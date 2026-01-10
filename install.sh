#!/bin/bash
#
# Claude Code Hooks Installer
# ============================
# Installs Ralph-style autonomous hooks to any project.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main/install.sh | bash -s /path/to/project
#   curl -sL https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main/install.sh | bash -s .
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# GitHub raw URL base
GITHUB_RAW="https://raw.githubusercontent.com/norvinteo/claude-code-hooks/main"

# Target project
TARGET_PROJECT="${1:-.}"

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}           Claude Code Hooks Installer                ${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# Validate and resolve target
if [ ! -d "$TARGET_PROJECT" ]; then
    echo -e "${YELLOW}Creating directory: $TARGET_PROJECT${NC}"
    mkdir -p "$TARGET_PROJECT"
fi

TARGET_PROJECT="$(cd "$TARGET_PROJECT" && pwd)"
TARGET_HOOKS="$TARGET_PROJECT/.claude/hooks"

echo -e "${YELLOW}Installing to:${NC} $TARGET_PROJECT"
echo ""

# Create directories
echo -e "${GREEN}Creating directories...${NC}"
mkdir -p "$TARGET_HOOKS"
mkdir -p "$TARGET_HOOKS/archive"
mkdir -p "$TARGET_PROJECT/progress"

# Hook files to download
HOOK_FILES=(
    "plan_initializer.py"
    "continuation_enforcer.py"
    "inject_plan_context.py"
    "todo_sync.py"
    "plan_tracker.py"
    "task_monitor.py"
    "cost_tracker.py"
    "stop_verifier.py"
    "completion_validator.py"
    "session_cleanup.py"
    "agent_complete_notify.py"
    "auto_continue.sh"
)

# Download hook files
echo -e "${GREEN}Downloading hook files...${NC}"
for file in "${HOOK_FILES[@]}"; do
    echo -n "  Downloading $file... "
    if curl -sL "$GITHUB_RAW/hooks/$file" -o "$TARGET_HOOKS/$file" 2>/dev/null; then
        # Replace placeholder with actual project path
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|{{PROJECT_DIR}}|$TARGET_PROJECT|g" "$TARGET_HOOKS/$file"
        else
            sed -i "s|{{PROJECT_DIR}}|$TARGET_PROJECT|g" "$TARGET_HOOKS/$file"
        fi
        chmod +x "$TARGET_HOOKS/$file"
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
    fi
done

# Download config files
echo -e "${GREEN}Downloading config files...${NC}"
for file in "config.json" "plan_state.json"; do
    echo -n "  Downloading $file... "
    if curl -sL "$GITHUB_RAW/config/$file" -o "$TARGET_HOOKS/$file" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
    fi
done

# Create settings.json
echo -e "${GREEN}Creating settings.json...${NC}"
cat > "$TARGET_PROJECT/.claude/settings.json" << EOF
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
echo "  OK"

echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo "Files installed to: $TARGET_HOOKS"
echo ""
echo "Usage:"
echo "  /plan <task name>     - Start a new plan"
echo "  /showplan             - Show current plan status"
echo "  /clearplan            - Clear the plan"
echo ""
echo -e "${YELLOW}Autonomous Mode (tmux):${NC}"
echo "  1. Start Claude in tmux:  tmux new -s claude"
echo "  2. In another terminal:   $TARGET_HOOKS/auto_continue.sh claude"
echo "  The script auto-sends 'c' when stop is blocked by incomplete tasks."
echo ""
echo "Configuration: $TARGET_HOOKS/config.json"
echo ""
echo -e "${YELLOW}Optional: Set environment variables for notifications:${NC}"
echo "  export SLACK_WEBHOOK_URL='https://hooks.slack.com/...'"
echo "  export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'"
echo "  export TELEGRAM_BOT_TOKEN='...' TELEGRAM_CHAT_ID='...'"
echo ""
